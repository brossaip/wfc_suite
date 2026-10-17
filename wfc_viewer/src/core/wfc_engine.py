"""
Wave Function Collapse engine with pause/resume support.
"""

import random
from enum import Enum, auto
from collections import deque
from itertools import combinations
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal, QTimer

from .tile import TileAtlas


class EngineState(Enum):
    """WFC engine states."""
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    FINISHED = auto()
    CONTRADICTION = auto()


@dataclass
class CellState:
    """State of a single cell in the WFC grid."""
    x: int
    y: int
    possibilities: Set[str] = field(default_factory=set)
    collapsed_tile: Optional[str] = None
    locked: bool = False  # User-placed tile, cannot be changed
    
    @property
    def is_collapsed(self) -> bool:
        return self.collapsed_tile is not None
    
    @property
    def entropy(self) -> int:
        """Number of remaining possibilities (lower = more constrained)."""
        if self.is_collapsed:
            return 0
        return len(self.possibilities)


@dataclass
class NeighborConstraint:
    """What one collapsed neighbour allows a cell to be."""
    side: str
    pos: Tuple[int, int]
    tile_id: str
    locked: bool
    allowed: Set[str]  # tiles the cell may take because of this neighbour
    neighbor_permits: Set[str]  # tiles the neighbour allows on the side facing the cell
    cell_permits: Set[str]  # tiles that list the neighbour on the side facing the neighbour


@dataclass
class Decision:
    """One random collapse choice, kept so it can be undone on contradiction."""
    pos: Tuple[int, int]
    options: List[str]
    tried: Set[str] = field(default_factory=set)
    # First-touched state per cell during this decision: pos -> (possibilities, collapsed_tile)
    changes: Dict[Tuple[int, int], Tuple[Set[str], Optional[str]]] = field(default_factory=dict)


class WFCEngine(QObject):
    """
    Wave Function Collapse algorithm with real-time visualization support.
    
    Signals:
        cell_collapsed(x, y, tile_id): Emitted when a cell is collapsed
        cell_updated(x, y): Emitted when cell possibilities change
        contradiction_found(x, y): Emitted when a contradiction is found
        state_changed(state): Emitted when engine state changes
        finished(success): Emitted when collapse completes
        progress_updated(collapsed, total): Emitted on progress change
    """
    
    cell_collapsed = Signal(int, int, str)
    cell_updated = Signal(int, int)
    contradiction_found = Signal(int, int)
    state_changed = Signal(EngineState)
    finished = Signal(bool)
    progress_updated = Signal(int, int)
    stuck = Signal(int, int)  # run paused: retries made no progress near (x, y)

    MAX_BACKTRACKS = 2000
    STUCK_RETRIES = 50  # retries without new progress before the run pauses

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.atlas: Optional[TileAtlas] = None
        self.width: int = 0
        self.height: int = 0
        self.cells: Dict[Tuple[int, int], CellState] = {}
        
        self._state = EngineState.IDLE
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._step_delay = 50  # milliseconds between steps
        
        self._collapsed_count = 0
        self._total_cells = 0

        self._history: List[Decision] = []
        self._backtracks = 0
        self._dead: Set[Tuple[int, int]] = set()  # crosses the run skips
        self._best_collapsed = -1
        self._retries_since_best = 0
        self._starts: List[Tuple[int, int]] = []  # cells the user marked while paused
        self._start_dist: Dict[Tuple[int, int], int] = {}  # steps from the nearest start

    @property
    def backtracks(self) -> int:
        """Number of backtracking retries since the last manual edit or reset."""
        return self._backtracks

    @property
    def state(self) -> EngineState:
        return self._state
    
    @state.setter
    def state(self, value: EngineState):
        if self._state != value:
            self._state = value
            self.state_changed.emit(value)
    
    def set_speed(self, delay_ms: int):
        """Set delay between collapse steps in milliseconds."""
        self._step_delay = max(1, delay_ms)
        if self._timer.isActive():
            self._timer.setInterval(self._step_delay)
    
    def initialize(self, atlas: TileAtlas, width: int, height: int):
        """
        Initialize the grid with all possibilities.
        
        Args:
            atlas: TileAtlas with tiles and rules
            width: Grid width
            height: Grid height
        """
        self.atlas = atlas
        self.width = width
        self.height = height
        self.cells.clear()
        self._collapsed_count = 0
        self._total_cells = width * height
        self._dead = set()
        self._set_starts([])
        self._clear_history()
        
        # Get all enabled tile IDs
        enabled_tiles = atlas.get_enabled_tile_ids()
        
        # Initialize each cell with all possibilities
        for y in range(height):
            for x in range(width):
                self.cells[(x, y)] = CellState(
                    x=x, y=y,
                    possibilities=enabled_tiles.copy()
                )
        
        self.state = EngineState.IDLE
        self.progress_updated.emit(0, self._total_cells)
    
    def lock_cell(self, x: int, y: int, tile_id: str, start_point: bool = False):
        """
        Lock a cell to a specific tile (user-placed constraint).
        This also propagates constraints to neighbors.
        start_point: the solver grows outward from this cell first.
        """
        if (x, y) not in self.cells:
            return

        # Manual edits invalidate the decision history
        self._clear_history()
        self._dead.discard((x, y))
        if self.state in (EngineState.FINISHED, EngineState.CONTRADICTION):
            self.state = EngineState.IDLE

        cell = self.cells[(x, y)]
        was_collapsed = cell.is_collapsed
        cell.collapsed_tile = tile_id
        cell.locked = True
        cell.possibilities = {tile_id}
        if start_point:
            self._set_starts(self._starts + [(x, y)])

        if not was_collapsed:
            self._collapsed_count += 1
        
        self.cell_collapsed.emit(x, y, tile_id)
        self.progress_updated.emit(self._collapsed_count, self._total_cells)
        
        # Propagate constraints
        self._propagate(x, y)
    
    def unlock_cell(self, x: int, y: int):
        """Unlock a cell and restore its possibilities."""
        if (x, y) not in self.cells:
            return

        # Manual edits invalidate the decision history
        self._clear_history()
        self._dead.discard((x, y))
        self._drop_starts([(x, y)])

        cell = self.cells[(x, y)]
        was_collapsed = cell.is_collapsed
        was_contradiction = len(cell.possibilities) == 0
        
        cell.locked = False
        cell.collapsed_tile = None
        cell.possibilities = self.atlas.get_enabled_tile_ids().copy()
        
        if was_collapsed:
            self._collapsed_count -= 1
        
        # If grid was finished or had contradiction, re-enable controls
        if was_collapsed or was_contradiction:
            if self.state in (EngineState.FINISHED, EngineState.CONTRADICTION):
                self.state = EngineState.IDLE
        
        self.cell_updated.emit(x, y)
        self.progress_updated.emit(self._collapsed_count, self._total_cells)
        
        # Re-propagate from neighbors
        for nx, ny in self._get_neighbors(x, y):
            if self.cells[(nx, ny)].is_collapsed:
                self._propagate(nx, ny)
    
    def clear_cell_and_forcing_neighbors(self, x: int, y: int) -> Tuple[List[Tuple[int, int]], int]:
        """
        Clear a cell so it can take a different tile. If its neighbours leave it at most one option,
        also clear the fewest neighbours needed to free it. Cleared cells stay empty; propagation
        does not refill them.
        Returns (cleared positions, how many of them were locked).
        """
        if (x, y) not in self.cells or self.atlas is None:
            return [], 0

        enabled = self.atlas.get_enabled_tile_ids()
        constraints = sorted(self.get_neighbor_constraints(x, y), key=lambda c: len(c.allowed))

        def open_options(ignored: Set[Tuple[int, int]]) -> Set[str]:
            options = set(enabled)
            for c in constraints:
                if c.pos not in ignored:
                    options &= c.allowed
            return options

        ignored: Set[Tuple[int, int]] = set()
        for c in constraints:
            if len(open_options(ignored)) > 1:
                break
            ignored.add(c.pos)

        to_clear = [(x, y)] + sorted(ignored)
        locked_count = 0
        for pos in to_clear:
            cell = self.cells[pos]
            if cell.is_collapsed:
                self._collapsed_count -= 1
            if cell.locked:
                locked_count += 1
            cell.locked = False
            cell.collapsed_tile = None
            cell.possibilities = set(enabled)

        self._drop_starts(to_clear)

        # Recompute options for every open cell from the placed cells that remain
        for cell in self.cells.values():
            if not cell.is_collapsed:
                cell.possibilities = self.get_valid_tiles_for_cell(cell.x, cell.y)

        self._clear_history()
        if self.state in (EngineState.FINISHED, EngineState.CONTRADICTION):
            self.state = EngineState.IDLE

        for pos in to_clear:
            self.cell_updated.emit(pos[0], pos[1])
        self.progress_updated.emit(self._collapsed_count, self._total_cells)
        return to_clear, locked_count

    def start(self):
        """Start or resume the collapse process."""
        if self.state in (EngineState.FINISHED, EngineState.CONTRADICTION):
            return
        
        self.state = EngineState.RUNNING
        self._timer.start(self._step_delay)
    
    def pause(self):
        """Pause the collapse process."""
        if self.state == EngineState.RUNNING:
            self._timer.stop()
            self.state = EngineState.PAUSED
    
    def step(self):
        """Perform a single collapse step (manual stepping)."""
        if self.state in (EngineState.FINISHED, EngineState.CONTRADICTION):
            return
        
        self._step()
    
    def reset(self):
        """Reset the grid, keeping locked cells."""
        if self.atlas is None:
            return
        
        self._timer.stop()
        
        # Save locked cells
        locked_cells = {
            pos: cell.collapsed_tile 
            for pos, cell in self.cells.items() 
            if cell.locked
        }
        
        # Re-initialize
        self.initialize(self.atlas, self.width, self.height)
        
        # Restore locked cells
        for (x, y), tile_id in locked_cells.items():
            self.lock_cell(x, y, tile_id)
    
    def clear_all(self):
        """Clear all cells including locked ones."""
        if self.atlas is None:
            return
        
        self._timer.stop()
        self.initialize(self.atlas, self.width, self.height)
    
    def _step(self):
        """Perform one collapse iteration."""
        # Find cell with lowest entropy (most constrained)
        best_key = None
        candidates = []
        
        for pos, cell in self.cells.items():
            if cell.is_collapsed or pos in self._dead:
                continue
            
            entropy = cell.entropy
            if entropy == 0:
                # Contradiction - no possibilities left
                self._backtrack(pos)
                return
            
            # Grow outward from user start points first; with none, this is entropy alone
            key = (self._start_dist.get(pos, 0), entropy)
            if best_key is None or key < best_key:
                best_key = key
                candidates = [pos]
            elif key == best_key:
                candidates.append(pos)
        
        if not candidates:
            # Every open cell is collapsed; crosses, if any, are reported as unresolved
            self._timer.stop()
            self.state = EngineState.FINISHED
            self.finished.emit(not self.cross_positions())
            return
        
        # Pick random cell among lowest entropy candidates
        x, y = random.choice(candidates)
        cell = self.cells[(x, y)]
        
        # Recalculate valid possibilities RIGHT NOW based on all collapsed neighbors
        # This ensures we have the most up-to-date constraints
        valid_now = self.atlas.get_enabled_tile_ids().copy()
        for nx, ny, side in self._get_neighbors_with_sides(x, y):
            neighbor = self.cells.get((nx, ny))
            if neighbor is None or not neighbor.is_collapsed:
                continue
            neighbor_tile = neighbor.collapsed_tile
            opposite = {'left': 'right', 'right': 'left',
                       'top': 'bottom', 'bottom': 'top'}[side]
            # Neighbor must allow me
            neighbor_allows = set(self.atlas.get_valid_neighbors(neighbor_tile, opposite).keys())
            # I must allow neighbor  
            i_allow = self.atlas.get_tiles_allowing_neighbor(side, neighbor_tile)
            
            valid_now &= neighbor_allows
            valid_now &= i_allow
        
        if not valid_now:
            self._backtrack((x, y))
            return

        # Record the decision so it can be undone, then collapse it
        decision = Decision(pos=(x, y), options=list(valid_now))
        self._history.append(decision)
        contradiction = self._apply_choice(decision, random.choice(decision.options))
        if contradiction is not None:
            self._backtrack(contradiction)
        else:
            self._note_progress()

    def _apply_choice(self, decision: Decision, tile_id: str) -> Optional[Tuple[int, int]]:
        """Collapse the decision's cell to tile_id and propagate. Returns a contradiction position, if any."""
        x, y = decision.pos
        decision.tried.add(tile_id)

        cell = self.cells[(x, y)]
        self._record(cell)
        cell.collapsed_tile = tile_id
        cell.possibilities = {tile_id}
        self._collapsed_count += 1

        self.cell_collapsed.emit(x, y, tile_id)
        self.progress_updated.emit(self._collapsed_count, self._total_cells)

        return self._propagate(x, y)

    def _backtrack(self, pos: Tuple[int, int]):
        """
        Undo decisions until one has an untried option that works.
        Gives up (showing a contradiction at pos) when history runs out or the retry limit is hit.
        """
        while self._history:
            decision = self._history[-1]
            remaining = [t for t in decision.options if t not in decision.tried]

            if not remaining:
                # Every option of this decision failed: undo it and go up one level
                self._restore(decision)
                self._history.pop()
                continue

            if self._retries_since_best >= self.STUCK_RETRIES:
                self._pause_stuck(pos)
                return

            if self._backtracks >= self.MAX_BACKTRACKS:
                break

            self._restore(decision)
            self._backtracks += 1
            self._retries_since_best += 1
            if self._apply_choice(decision, random.choice(remaining)) is None:
                self._note_progress()
                return

        self._mark_cross(pos)

    def _mark_cross(self, pos: Tuple[int, int]):
        """Give up on pos: it stays empty as a cross and the run continues elsewhere."""
        self._dead.add(pos)
        self._history.clear()
        self._backtracks = 0
        cell = self.cells.get(pos)
        if cell is not None and not cell.is_collapsed:
            cell.possibilities = set()
        self.contradiction_found.emit(pos[0], pos[1])
        self.cell_updated.emit(pos[0], pos[1])

    def _pause_stuck(self, pos: Tuple[int, int]):
        """Pause because retries keep failing without new progress; the user marks a new start cell."""
        self._timer.stop()
        self.state = EngineState.PAUSED
        self.stuck.emit(pos[0], pos[1])

    def _note_progress(self):
        """Reset the stuck counter when the run reaches a new maximum of collapsed cells."""
        if self._collapsed_count > self._best_collapsed:
            self._best_collapsed = self._collapsed_count
            self._retries_since_best = 0

    def is_cross(self, x: int, y: int) -> bool:
        """True if (x, y) is an open cell the run has given up on."""
        cell = self.cells.get((x, y))
        return cell is not None and not cell.is_collapsed and (x, y) in self._dead

    def cross_positions(self) -> List[Tuple[int, int]]:
        return sorted(p for p in self._dead if self.is_cross(*p))

    def _restore(self, decision: Decision):
        """Undo all cell changes made under a decision."""
        for pos, (possibilities, tile_id) in decision.changes.items():
            cell = self.cells[pos]
            cell.possibilities = set(possibilities)
            cell.collapsed_tile = tile_id
            self.cell_updated.emit(pos[0], pos[1])
        decision.changes = {}

        self._collapsed_count = sum(1 for c in self.cells.values() if c.is_collapsed)
        self.progress_updated.emit(self._collapsed_count, self._total_cells)

    def _record(self, cell: CellState):
        """Remember a cell's state before its first change under the current decision."""
        if not self._history:
            return
        self._history[-1].changes.setdefault(
            (cell.x, cell.y), (set(cell.possibilities), cell.collapsed_tile)
        )

    def _clear_history(self):
        self._history.clear()
        self._backtracks = 0
        self._retries_since_best = 0
        self._best_collapsed = -1

    def force_place(self, x: int, y: int, tile_id: str, start_point: bool = False):
        """
        Place tile_id on a cell even if it conflicts with its neighbors.
        Unlocked neighbors that conflict with it are cleared; locked ones are kept.
        """
        if (x, y) not in self.cells or self.atlas is None:
            return

        for nx, ny, side in self._get_neighbors_with_sides(x, y):
            neighbor = self.cells[(nx, ny)]
            if not neighbor.is_collapsed or neighbor.locked:
                continue

            opposite = {'left': 'right', 'right': 'left',
                       'top': 'bottom', 'bottom': 'top'}[side]
            compatible = (
                self.atlas.can_be_neighbor(tile_id, side, neighbor.collapsed_tile)
                and self.atlas.can_be_neighbor(neighbor.collapsed_tile, opposite, tile_id)
            )
            if not compatible:
                self.unlock_cell(nx, ny)

        self.lock_cell(x, y, tile_id, start_point)
    
    def _set_starts(self, starts: List[Tuple[int, int]]):
        """Replace the start points and recompute each cell's distance to the nearest one."""
        self._starts = list(starts)
        self._start_dist = {}
        queue = deque()
        for p in self._starts:
            if p not in self._start_dist:
                self._start_dist[p] = 0
                queue.append(p)
        while queue:
            x, y = queue.popleft()
            for nx, ny, _ in self._get_neighbors_with_sides(x, y):
                if (nx, ny) not in self._start_dist:
                    self._start_dist[(nx, ny)] = self._start_dist[(x, y)] + 1
                    queue.append((nx, ny))

    def _drop_starts(self, positions: List[Tuple[int, int]]):
        """Forget any start points among positions (they were cleared)."""
        gone = set(positions)
        if any(p in gone for p in self._starts):
            self._set_starts([p for p in self._starts if p not in gone])

    def _weighted_choice(self, possibilities: Set[str]) -> str:
        """Choose a tile weighted by rule weights."""
        if not possibilities:
            raise ValueError("No possibilities to choose from")
        
        # For simplicity, use uniform random for now
        # Could be enhanced to use actual weights from rules
        return random.choice(list(possibilities))
    
    def _propagate(self, start_x: int, start_y: int) -> Optional[Tuple[int, int]]:
        """Propagate constraints from collapsed cells."""
        from collections import deque
        queue = deque()
        
        # Add all uncollapsed neighbors of the starting cell
        for nx, ny, _ in self._get_neighbors_with_sides(start_x, start_y):
            neighbor = self.cells.get((nx, ny))
            if neighbor and not neighbor.is_collapsed:
                queue.append((nx, ny))
        
        while queue:
            x, y = queue.popleft()
            
            cell = self.cells.get((x, y))
            # Crosses are skipped: an empty cell the run gave up on must not block propagation again
            if cell is None or cell.is_collapsed or (x, y) in self._dead:
                continue
            
            # Recalculate ALL valid possibilities for this cell
            # based on ALL its collapsed neighbors
            valid = self.atlas.get_enabled_tile_ids().copy()
            
            for nx, ny, side in self._get_neighbors_with_sides(x, y):
                neighbor = self.cells.get((nx, ny))
                if neighbor is None or not neighbor.is_collapsed:
                    continue
                
                neighbor_tile = neighbor.collapsed_tile
                opposite = {'left': 'right', 'right': 'left',
                           'top': 'bottom', 'bottom': 'top'}[side]
                
                # 1. Neighbor must allow me: I'm on neighbor's 'opposite' side
                neighbor_allows = set(self.atlas.get_valid_neighbors(neighbor_tile, opposite).keys())
                
                # 2. I must allow neighbor: neighbor is on my 'side'
                i_allow = self.atlas.get_tiles_allowing_neighbor(side, neighbor_tile)
                
                # Both constraints
                valid &= neighbor_allows
                valid &= i_allow
            
            # Update if changed
            if valid != cell.possibilities:
                self._record(cell)
                cell.possibilities = valid
                self.cell_updated.emit(x, y)

                if len(valid) == 0:
                    # Contradiction
                    return (x, y)
                elif len(valid) == 1:
                    # Auto-collapse
                    tile = next(iter(valid))
                    cell.collapsed_tile = tile
                    self._collapsed_count += 1
                    self.cell_collapsed.emit(x, y, tile)
                    self.progress_updated.emit(self._collapsed_count, self._total_cells)
                    # Add neighbors of newly collapsed cell
                    for nnx, nny, _ in self._get_neighbors_with_sides(x, y):
                        nn = self.cells.get((nnx, nny))
                        if nn and not nn.is_collapsed:
                            queue.append((nnx, nny))
                else:
                    # Possibilities reduced, propagate to neighbors
                    for nnx, nny, _ in self._get_neighbors_with_sides(x, y):
                        nn = self.cells.get((nnx, nny))
                        if nn and not nn.is_collapsed:
                            queue.append((nnx, nny))

        return None
    
    def _get_neighbors(self, x: int, y: int) -> List[Tuple[int, int]]:
        """Get valid neighbor positions."""
        neighbors = []
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.width and 0 <= ny < self.height:
                neighbors.append((nx, ny))
        return neighbors
    
    def _get_neighbors_with_sides(
        self, x: int, y: int
    ) -> List[Tuple[int, int, str]]:
        """Get valid neighbors with the side they're on."""
        neighbors = []
        directions = [
            (-1, 0, 'left'),
            (1, 0, 'right'),
            (0, -1, 'top'),
            (0, 1, 'bottom')
        ]
        for dx, dy, side in directions:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.width and 0 <= ny < self.height:
                neighbors.append((nx, ny, side))
        return neighbors
    
    def get_cell(self, x: int, y: int) -> Optional[CellState]:
        """Get cell state at position."""
        return self.cells.get((x, y))
    
    def get_valid_tiles_for_cell(self, x: int, y: int) -> Set[str]:
        """
        Get tiles valid for a cell given its collapsed neighbors.
        
        For each collapsed neighbor N on side S, tile T is valid if:
        - N allows T on opposite(S): rule {tile: N, side: opposite(S), neighbor: T}
        - T allows N on S: rule {tile: T, side: S, neighbor: N}
        """
        if self.atlas is None:
            return set()
        
        valid = self.atlas.get_enabled_tile_ids().copy()
        
        for nx, ny, side in self._get_neighbors_with_sides(x, y):
            neighbor = self.cells.get((nx, ny))
            if neighbor is None or not neighbor.is_collapsed:
                continue
            
            neighbor_tile = neighbor.collapsed_tile
            opposite = {'left': 'right', 'right': 'left',
                       'top': 'bottom', 'bottom': 'top'}[side]
            
            # 1. Neighbor must allow me
            neighbor_allows = set(self.atlas.get_valid_neighbors(neighbor_tile, opposite).keys())
            
            # 2. I must allow neighbor
            i_allow = self.atlas.get_tiles_allowing_neighbor(side, neighbor_tile)
            
            valid &= neighbor_allows
            valid &= i_allow
        
        return valid
    
    def get_neighbor_constraints(self, x: int, y: int) -> List[NeighborConstraint]:
        """Constraint each collapsed neighbour puts on cell (x, y), in both adjacency directions."""
        if self.atlas is None:
            return []

        constraints = []
        for nx, ny, side in self._get_neighbors_with_sides(x, y):
            neighbor = self.cells[(nx, ny)]
            if not neighbor.is_collapsed:
                continue

            opposite = {'left': 'right', 'right': 'left',
                       'top': 'bottom', 'bottom': 'top'}[side]
            neighbor_permits = set(self.atlas.get_valid_neighbors(neighbor.collapsed_tile, opposite).keys())
            cell_permits = self.atlas.get_tiles_allowing_neighbor(side, neighbor.collapsed_tile)
            constraints.append(NeighborConstraint(
                side=side,
                pos=(nx, ny),
                tile_id=neighbor.collapsed_tile,
                locked=neighbor.locked,
                allowed=neighbor_permits & cell_permits,
                neighbor_permits=neighbor_permits,
                cell_permits=cell_permits,
            ))
        return constraints

    @staticmethod
    def _missing_rule(c: NeighborConstraint) -> str:
        """Which one-directional rule is absent for this neighbour, or '' if both directions have rules."""
        opposite = {'left': 'right', 'right': 'left', 'top': 'bottom', 'bottom': 'top'}[c.side]
        if not c.neighbor_permits:
            return f"{c.tile_id} has no rules on its {opposite} side"
        if not c.cell_permits:
            return f"no tile has {c.tile_id} on its {c.side} side"
        return ""

    def find_minimal_conflict(self, x: int, y: int) -> List[NeighborConstraint]:
        """Smallest group of neighbours whose constraints together leave no tile. Empty if none."""
        constraints = self.get_neighbor_constraints(x, y)
        for size in range(1, len(constraints) + 1):
            for group in combinations(constraints, size):
                if not set.intersection(*(c.allowed for c in group)):
                    return list(group)
        return []

    def describe_conflict(self, x: int, y: int) -> str:
        """Human-readable explanation of why cell (x, y) has no valid tile."""
        constraints = self.get_neighbor_constraints(x, y)
        if not constraints:
            return f"Cell ({x}, {y}): no collapsed neighbours to blame."

        lines = [f"Cell ({x}, {y}) has no valid tile.", "Neighbours:"]
        for c in constraints:
            tag = " [locked]" if c.locked else ""
            permitted = sorted(c.allowed)
            shown = ", ".join(permitted[:8]) + (", …" if len(permitted) > 8 else "")
            lines.append(
                f"  {c.side} ({c.pos[0]}, {c.pos[1]}): {c.tile_id}{tag} "
                f"→ cell may be: {shown or 'none'}"
            )

        culprits = self.find_minimal_conflict(x, y)
        if culprits:
            names = " + ".join(f"{c.side} {c.tile_id} at ({c.pos[0]}, {c.pos[1]})" for c in culprits)
            lines.append(f"Smallest conflicting set: {names}")
            missing = [r for r in (self._missing_rule(c) for c in culprits) if r]
            if missing:
                lines.extend(f"Missing rule: {r}" for r in missing)
            elif len(culprits) == 1:
                lines.append(f"Missing rule: {culprits[0].tile_id}'s rules on its two sides disagree")
            else:
                lines.append("Missing rule: these neighbours have options, but none is shared by all")
        else:
            lines.append("No direct neighbour conflict: the cause is an earlier choice further away.")
        return "\n".join(lines)

    def explain_tile(self, x: int, y: int, tile_id: str) -> str:
        """Why tile_id cannot go at (x, y), one line per neighbour that rejects it. Empty if none does."""
        reasons = []
        for c in self.get_neighbor_constraints(x, y):
            opposite = {'left': 'right', 'right': 'left', 'top': 'bottom', 'bottom': 'top'}[c.side]
            if tile_id not in c.neighbor_permits:
                reasons.append(f"{c.tile_id} has no rule allowing {tile_id} on its {opposite} side")
            elif tile_id not in c.cell_permits:
                reasons.append(f"{tile_id} has no rule listing {c.tile_id} on its {c.side} side")
        return "\n".join(reasons)

    def validate_grid(self) -> List[str]:
        """
        Validate all adjacencies in the current grid.
        Returns list of error messages (empty if valid).
        """
        errors = []
        
        if self.atlas is None:
            return ["No atlas loaded"]
        
        for y in range(self.height):
            for x in range(self.width):
                cell = self.get_cell(x, y)
                if cell is None or not cell.is_collapsed:
                    continue
                
                tile_id = cell.collapsed_tile
                
                # Check each neighbor
                for nx, ny, side in self._get_neighbors_with_sides(x, y):
                    neighbor = self.get_cell(nx, ny)
                    if neighbor is None or not neighbor.is_collapsed:
                        continue
                    
                    neighbor_tile = neighbor.collapsed_tile
                    
                    # Check if this tile allows the neighbor on this side
                    allowed = self.atlas.get_valid_neighbors(tile_id, side)
                    if neighbor_tile not in allowed:
                        errors.append(
                            f"({x},{y}) '{tile_id}' does not allow '{neighbor_tile}' on {side}"
                        )
        
        return errors

