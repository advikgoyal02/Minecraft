from __future__ import division

import sys
import math
import random
import time
import traceback

import pyglet
from collections import deque
from pyglet import image
from pyglet import gl
from pyglet.graphics import TextureGroup
from pyglet.window import key, mouse

from noise_gen import NoiseGen

TICKS_PER_SEC = 60

# Size of sectors used to ease block loading.
SECTOR_SIZE = 16

# Movement variables
WALKING_SPEED = 5
FLYING_SPEED = 15
CROUCH_SPEED = 2
SPRINT_SPEED = 7
SPRINT_FOV = SPRINT_SPEED / 2

GRAVITY = 20.0
MAX_JUMP_HEIGHT = 1.0  # About the height of a block.
JUMP_SPEED = math.sqrt(2 * GRAVITY * MAX_JUMP_HEIGHT)
TERMINAL_VELOCITY = 50

# Player variables
PLAYER_HEIGHT = 2
MAX_JUMP_HEIGHT = 1.0
PLAYER_FOV = 70  # Default field of view for the player

if sys.version_info[0] >= 3:
    xrange = range


def cube_vertices(x, y, z, n):
    """Return the vertices of the cube at position x, y, z with size 2*n.
    This returns 24 vertices (4 per face) so per-face UVs/colors can be applied.
    """
    return [
        # top
        x - n, y + n, z - n, x - n, y + n, z + n, x + n, y + n, z + n, x + n, y + n, z - n,
        # bottom
        x - n, y - n, z - n, x + n, y - n, z - n, x + n, y - n, z + n, x - n, y - n, z + n,
        # left
        x - n, y - n, z - n, x - n, y - n, z + n, x - n, y + n, z + n, x - n, y + n, z - n,
        # right
        x + n, y - n, z + n, x + n, y - n, z - n, x + n, y + n, z - n, x + n, y + n, z + n,
        # front
        x - n, y - n, z + n, x + n, y - n, z + n, x + n, y + n, z + n, x - n, y + n, z + n,
        # back
        x + n, y - n, z - n, x - n, y - n, z - n, x - n, y + n, z - n, x + n, y + n, z - n
    ]


def tex_coord(x, y, n=4):
    """Return the bounding vertices of the texture square."""
    m = 1.0 / n
    dx = x * m
    dy = y * m
    return dx, dy, dx + m, dy, dx + m, dy + m, dx, dy + m


def tex_coords(top, bottom, side):
    """Return a list of the texture squares for the top, bottom and side."""
    top = tex_coord(*top)
    bottom = tex_coord(*bottom)
    side = tex_coord(*side)
    result = []
    result.extend(top)
    result.extend(bottom)
    result.extend(side * 4)
    return result


TEXTURE_PATH = 'texture.png'

GRASS = tex_coords((1, 0), (0, 1), (0, 0))
SAND = tex_coords((1, 1), (1, 1), (1, 1))
BRICK = tex_coords((2, 0), (2, 0), (2, 0))
STONE = tex_coords((2, 1), (2, 1), (2, 1))
WOOD = tex_coords((3, 1), (3, 1), (3, 1))
LEAF = tex_coords((3, 0), (3, 0), (3, 0))
WATER = tex_coords((0, 2), (0, 2), (0, 2))

FACES = [
    (0, 1, 0),
    (0, -1, 0),
    (-1, 0, 0),
    (1, 0, 0),
    (0, 0, 1),
    (0, 0, -1),
]


def normalize(position):
    """Return the block containing the arbitrary-precision `position`."""
    x, y, z = position
    x, y, z = (int(round(x)), int(round(y)), int(round(z)))
    return (x, y, z)


def sectorize(position):
    """Return the sector for the given `position`."""
    x, y, z = normalize(position)
    x, y, z = x // SECTOR_SIZE, y // SECTOR_SIZE, z // SECTOR_SIZE
    return (x, 0, z)


class Model(object):
    def __init__(self):
        # A Batch is a collection of vertex lists for batched rendering.
        self.batch = pyglet.graphics.Batch()

        # A TextureGroup manages an OpenGL texture.
        # ensure texture exists at TEXTURE_PATH
        try:
            self.group = TextureGroup(image.load(TEXTURE_PATH).get_texture())
        except Exception as e:
            print("Error loading texture:", e)
            raise

        # A mapping from position to the texture of the block at that position.
        self.world = {}

        # Same mapping as `world` but only contains blocks that are shown.
        self.shown = {}

        # Mapping from position to a pyglet `VertexList` for all shown blocks.
        self._shown = {}

        # Mapping from sector to a list of positions inside that sector.
        self.sectors = {}

        # Simple function queue implementation. The queue is populated with
        # _show_block() and _hide_block() calls
        self.queue = deque()

        self._initialize()

    def _initialize(self):
        """Initialize the world by placing all the blocks."""
        gen = NoiseGen(452692)

        n = 160  # make a smaller world for debugging
        s = 1    # step size

        heightMap = [0] * (n * n)
        for x in xrange(0, n, s):
            for z in xrange(0, n, s):
                # scale down the noise so heights are reasonable
                heightMap[z + x * n] = int(gen.getHeight(x, z) / 6)

        # Generate the world
        for x in xrange(0, n, s):
            for z in xrange(0, n, s):
                h = heightMap[z + x * n]
                if h < 4:
                    self.add_block((x, h, z), SAND, immediate=False)
                    for y in range(h, 4):
                        self.add_block((x, y, z), WATER, immediate=False)
                    continue
                if h < 6:
                    self.add_block((x, h, z), SAND, immediate=False)
                self.add_block((x, h, z), GRASS, immediate=False)
                for y in xrange(h - 1, 0, -1):
                    self.add_block((x, y, z), STONE, immediate=False)
                # Maybe add tree at this (x, z)
                if h > 6 and random.randrange(0, 1000) > 990:
                    treeHeight = random.randrange(3, 5)
                    # Tree trunk
                    for y in xrange(h + 1, h + treeHeight):
                        self.add_block((x, y, z), WOOD, immediate=False)
                    # Tree leaves
                    leafh = h + treeHeight
                    for lz in xrange(z - 1, z + 2):
                        for lx in xrange(x - 1, x + 2):
                            for ly in xrange(2):
                                self.add_block((lx, leafh + ly, lz), LEAF, immediate=False)

    def hit_test(self, position, vector, max_distance=8):
        """Ray-cast from position along vector; return (block, previous)."""
        m = 8
        x, y, z = position
        dx, dy, dz = vector
        previous = None
        for _ in xrange(max_distance * m):
            key = normalize((x, y, z))
            if key != previous and key in self.world:
                return key, previous
            previous = key
            x, y, z = x + dx / m, y + dy / m, z + dz / m
        return None, None

    def exposed(self, position):
        """Return True if any face of the block is exposed."""
        x, y, z = position
        for dx, dy, dz in FACES:
            if (x + dx, y + dy, z + dz) not in self.world:
                return True
        return False

    def add_block(self, position, texture, immediate=True):
        """Add a block with the given `texture` at `position`."""
        if position in self.world:
            self.remove_block(position, immediate)
        self.world[position] = texture
        self.sectors.setdefault(sectorize(position), []).append(position)
        if immediate:
            if self.exposed(position):
                self.show_block(position)
            self.check_neighbors(position)
        else:
            # queue showing of block
            self._enqueue(self._show_block, position, texture)

    def remove_block(self, position, immediate=True):
        """Remove the block at `position`."""
        if position in self.world:
            del self.world[position]
            self.sectors[sectorize(position)].remove(position)
            if immediate:
                if position in self.shown:
                    self.hide_block(position)
                self.check_neighbors(position)

    def check_neighbors(self, position):
        """Update visibility for neighbors of `position`."""
        x, y, z = position
        for dx, dy, dz in FACES:
            key = (x + dx, y + dy, z + dz)
            if key not in self.world:
                continue
            if self.exposed(key):
                if key not in self.shown:
                    self.show_block(key)
            else:
                if key in self.shown:
                    self.hide_block(key)

    def show_block(self, position, immediate=True):
        """Show the block at `position`."""
        texture = self.world[position]
        self.shown[position] = texture
        if immediate:
            self._show_block(position, texture)
        else:
            self._enqueue(self._show_block, position, texture)

    def _show_block(self, position, texture):
        """Private impl of `show_block` (modern Pyglet 2.x)."""
        x, y, z = position
        # vertex_data is 24 vertices (v3f) — 4 verts per face, 6 faces
        vertex_data = cube_vertices(x, y, z, 0.5)
        # texture_data should be 24 * 2 floats (u,v per vertex)
        texture_data = list(texture)

        try:
            # Build triangle indices (6 faces × 2 triangles = 12 triangles = 36 indices)
            # Each face has 4 consecutive vertices; convert quads -> 2 triangles
            indices = []
            for i in range(0, 24, 4):
                indices.extend([i, i + 1, i + 2, i, i + 2, i + 3])

            # Create a vertex list in the batch using indexed triangles and the texture group
            self._shown[position] = self.batch.add_indexed(
                24,                        # number of vertices
                gl.GL_TRIANGLES,           # primitive type
                self.group,                # texture group
                indices,                   # triangle indices
                ('v3f/static', vertex_data),
                ('t2f/static', texture_data)
            )
        except Exception as e:
            print("Error creating vertex list for", position, e)

    def hide_block(self, position, immediate=True):
        """Hide the block at `position` (doesn't remove from world)."""
        if position in self.shown:
            self.shown.pop(position)
        if immediate:
            self._hide_block(position)
        else:
            self._enqueue(self._hide_block, position)

    def _hide_block(self, position):
        """Private impl of `hide_block`."""
        if position in self._shown:
            self._shown.pop(position).delete()

    def show_sector(self, sector):
        """Draw all exposed blocks in the given sector."""
        for position in self.sectors.get(sector, []):
            if position not in self.shown and self.exposed(position):
                self.show_block(position, False)

    def hide_sector(self, sector):
        """Hide all shown blocks in the given sector."""
        for position in self.sectors.get(sector, []):
            if position in self.shown:
                self.hide_block(position, False)

    def change_sectors(self, before, after):
        """Move from sector `before` to sector `after` with padding."""
        before_set = set()
        after_set = set()
        pad = 4
        for dx in xrange(-pad, pad + 1):
            for dy in [0]:
                for dz in xrange(-pad, pad + 1):
                    if dx ** 2 + dy ** 2 + dz ** 2 > (pad + 1) ** 2:
                        continue
                    if before:
                        x, y, z = before
                        before_set.add((x + dx, y + dy, z + dz))
                    if after:
                        x, y, z = after
                        after_set.add((x + dx, y + dy, z + dz))
        show = after_set - before_set
        hide = before_set - after_set
        for sector in show:
            self.show_sector(sector)
        for sector in hide:
            self.hide_sector(sector)

    def _enqueue(self, func, *args):
        self.queue.append((func, args))

    def _dequeue(self):
        func, args = self.queue.popleft()
        func(*args)

    def process_queue(self):
        """Process queue while letting the game loop breathe."""
        start = time.process_time()
        while self.queue and time.process_time() - start < 1.0 / TICKS_PER_SEC:
            self._dequeue()

    def process_entire_queue(self):
        while self.queue:
            self._dequeue()


class Window(pyglet.window.Window):
    def __init__(self, *args, **kwargs):
        # create window (GL context created here)
        super(Window, self).__init__(*args, **kwargs)

        # Create the world model (now GL context exists)
        self.model = Model()
        # Process all queued block show calls immediately so things are visible
        self.model.process_entire_queue()

        # Whether or not the window exclusively captures the mouse.
        self.exclusive = False

        # When flying gravity has no effect and speed is increased.
        self.flying = False

        # Jump state flags
        self.jumping = False
        self.jumped = False

        # Crouch & sprint state
        self.crouch = False
        self.sprinting = False

        # FOV offset for sprint, etc.
        self.fov_offset = 0

        self.collision_types = {"top": False, "bottom": False, "right": False, "left": False}

        # [forward/back, left/right] strafing
        self.strafe = [0, 0]

        # Player start position
        # Put player near the generated terrain
        self.position = (16, 30, 16)

        # rotation: (yaw, pitch)
        self.rotation = (0, 0)

        # current sector
        self.sector = None

        # reticle & label
        self.reticle = None
        self.label = pyglet.text.Label(
            '', font_name='Arial', font_size=18,
            x=10, y=self.height - 10, anchor_x='left', anchor_y='top',
            color=(0, 0, 0, 255)
        )

        # create initial reticle immediately
        self.on_resize(self.width, self.height)

        # vertical velocity
        self.dy = 0

        # inventory
        self.inventory = [BRICK, GRASS, SAND, WOOD, LEAF]
        self.block = self.inventory[0]
        self.num_keys = [key._1, key._2, key._3, key._4, key._5, key._6, key._7, key._8, key._9, key._0]

        # main loop
        pyglet.clock.schedule_interval(self.update, 1.0 / TICKS_PER_SEC)

    def set_exclusive_mouse(self, exclusive):
        super(Window, self).set_exclusive_mouse(exclusive)
        self.exclusive = exclusive

    def get_sight_vector(self):
        x, y = self.rotation
        m = math.cos(math.radians(y))
        dy = math.sin(math.radians(y))
        dx = math.cos(math.radians(x - 90)) * m
        dz = math.sin(math.radians(x - 90)) * m
        return (dx, dy, dz)

    def get_motion_vector(self):
        if any(self.strafe):
            x, y = self.rotation
            strafe = math.degrees(math.atan2(*self.strafe))
            y_angle = math.radians(y)
            x_angle = math.radians(x + strafe)
            if self.flying:
                m = math.cos(y_angle)
                dy = math.sin(y_angle)
                if self.strafe[1]:
                    dy = 0.0
                    m = 1
                if self.strafe[0] > 0:
                    dy *= -1
                dx = math.cos(x_angle) * m
                dz = math.sin(x_angle) * m
            else:
                dy = 0.0
                dx = math.cos(x_angle)
                dz = math.sin(x_angle)
        else:
            dy = 0.0
            dx = 0.0
            dz = 0.0
        return (dx, dy, dz)

    def update(self, dt):
        try:
            self.model.process_queue()
            sector = sectorize(self.position)
            if sector != self.sector:
                self.model.change_sectors(self.sector, sector)
                if self.sector is None:
                    self.model.process_entire_queue()
                self.sector = sector
            m = 8
            dt = min(dt, 0.2)
            for _ in xrange(m):
                self._update(dt / m)
        except Exception:
            print("Error during update:")
            traceback.print_exc()

    def _update(self, dt):
        if self.flying:
            speed = FLYING_SPEED
        elif self.sprinting:
            speed = SPRINT_SPEED
        elif self.crouch:
            speed = CROUCH_SPEED
        else:
            speed = WALKING_SPEED

        if self.jumping:
            if self.collision_types["top"]:
                self.dy = JUMP_SPEED
                self.jumped = True
        else:
            if self.collision_types["top"]:
                self.jumped = False
        if self.jumped:
            speed += 0.7

        d = dt * speed  # distance covered this tick.
        dx, dy, dz = self.get_motion_vector()
        dx, dy, dz = dx * d, dy * d, dz * d

        # gravity
        if not self.flying:
            self.dy -= dt * GRAVITY
            self.dy = max(self.dy, -TERMINAL_VELOCITY)
            dy += self.dy * dt

        # collisions
        old_pos = self.position
        x, y, z = old_pos
        x, y, z = self.collide((x + dx, y + dy, z + dz), PLAYER_HEIGHT)
        self.position = (x, y, z)

        # stop sprint FOV when stopping
        if old_pos[0] - self.position[0] == 0 and old_pos[2] - self.position[2] == 0:
            disablefov = False
            if self.sprinting:
                disablefov = True
            self.sprinting = False
            if disablefov:
                self.fov_offset -= SPRINT_FOV

    def collide(self, position, height):
        """Basic AABB collision with blocks."""
        pad = 0.25
        p = list(position)
        np = normalize(position)
        self.collision_types = {"top": False, "bottom": False, "right": False, "left": False}
        for face in FACES:
            for i in xrange(3):
                if not face[i]:
                    continue
                d = (p[i] - np[i]) * face[i]
                if d < pad:
                    continue
                for dy in xrange(height):
                    op = list(np)
                    op[1] -= dy
                    op[i] += face[i]
                    if tuple(op) not in self.model.world:
                        continue
                    p[i] -= (d - pad) * face[i]
                    if face == (0, -1, 0):
                        self.collision_types["top"] = True
                        self.dy = 0
                    if face == (0, 1, 0):
                        self.collision_types["bottom"] = True
                        self.dy = 0
                    break
        return tuple(p)

    def on_mouse_press(self, x, y, button, modifiers):
        if self.exclusive:
            vector = self.get_sight_vector()
            block, previous = self.model.hit_test(self.position, vector)
            if (button == mouse.RIGHT) or ((button == mouse.LEFT) and (modifiers & key.MOD_CTRL)):
                if previous:
                    self.model.add_block(previous, self.block)
            elif button == pyglet.window.mouse.LEFT and block:
                texture = self.model.world[block]
                if texture != STONE:
                    self.model.remove_block(block)
        else:
            self.set_exclusive_mouse(True)

    def on_mouse_motion(self, x, y, dx, dy):
        if self.exclusive:
            m = 0.15
            xrot, yrot = self.rotation
            xrot, yrot = xrot + dx * m, yrot + dy * m
            yrot = max(-90, min(90, yrot))
            self.rotation = (xrot, yrot)

    def on_key_press(self, symbol, modifiers):
        if symbol == key.W:
            self.strafe[0] -= 1
        elif symbol == key.S:
            self.strafe[0] += 1
        elif symbol == key.A:
            self.strafe[1] -= 1
        elif symbol == key.D:
            self.strafe[1] += 1
        elif symbol == key.C:
            self.fov_offset -= 60.0
        elif symbol == key.SPACE:
            self.jumping = True
        elif symbol == key.ESCAPE:
            self.set_exclusive_mouse(False)
        elif symbol == key.LSHIFT:
            self.crouch = True
            if self.sprinting:
                self.fov_offset -= SPRINT_FOV
                self.sprinting = False
        elif symbol == key.R:
            if not self.crouch:
                if not self.sprinting:
                    self.fov_offset += SPRINT_FOV
                self.sprinting = True
        elif symbol == key.TAB:
            self.flying = not self.flying
        elif symbol in self.num_keys:
            index = (symbol - self.num_keys[0]) % len(self.inventory)
            self.block = self.inventory[index]

    def on_key_release(self, symbol, modifiers):
        if symbol == key.W:
            self.strafe[0] += 1
        elif symbol == key.S:
            self.strafe[0] -= 1
        elif symbol == key.A:
            self.strafe[1] += 1
        elif symbol == key.D:
            self.strafe[1] -= 1
        elif symbol == key.SPACE:
            self.jumping = False
        elif symbol == key.LSHIFT:
            self.crouch = False
        elif symbol == key.C:
            self.fov_offset += 60.0

    def on_resize(self, width, height):
        self.label.y = height - 10
        if self.reticle:
            self.reticle.delete()
        x, y = self.width // 2, self.height // 2
        n = 10
        self.reticle = pyglet.graphics.vertex_list(
            4,
            ('v2i', (x - n, y, x + n, y, x, y - n, x, y + n))
        )

    def set_2d(self):
        width, height = self.get_size()
        gl.glDisable(gl.GL_DEPTH_TEST)
        viewport = self.get_viewport_size()
        gl.glViewport(0, 0, max(1, viewport[0]), max(1, viewport[1]))
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glOrtho(0, max(1, width), 0, max(1, height), -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()

    def set_3d(self):
        width, height = self.get_size()
        gl.glEnable(gl.GL_DEPTH_TEST)
        viewport = self.get_viewport_size()
        gl.glViewport(0, 0, max(1, viewport[0]), max(1, viewport[1]))
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.gluPerspective(PLAYER_FOV + self.fov_offset, width / float(height), 0.1, 60.0)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        xrot, yrot = self.rotation
        gl.glRotatef(xrot, 0, 1, 0)
        gl.glRotatef(-yrot, math.cos(math.radians(xrot)), 0, math.sin(math.radians(xrot)))
        x, y, z = self.position
        if self.crouch:
            gl.glTranslatef(-x, -y + 0.2, -z)
        else:
            gl.glTranslatef(-x, -y, -z)

    def on_draw(self):
        try:
            self.clear()
            # debug print - will appear in terminal
            print("Player pos:", self.position, "Shown blocks:", len(self.model._shown))
            self.set_3d()
            gl.glColor3f(1, 1, 1)
            self.model.batch.draw()
            self.draw_focused_block()
            self.set_2d()
            self.draw_label()
            self.draw_reticle()
        except Exception:
            print("Error during drawing:")
            traceback.print_exc()

    def draw_focused_block(self):
        vector = self.get_sight_vector()
        block = self.model.hit_test(self.position, vector)[0]
        if block:
            x, y, z = block
            vertex_data = cube_vertices(x, y, z, 0.51)

            # Build triangle indices for the 24-vertex cube
            indices = []
            for i in range(0, 24, 4):
                indices.extend([i, i + 1, i + 2, i, i + 2, i + 3])

            # Temporary indexed vertex list for outline drawing
            # We draw triangles in line polygon mode to show wireframe outline
            try:
                vl = pyglet.graphics.vertex_list_indexed(
                    24,
                    indices,
                    ('v3f/static', vertex_data)
                )
                gl.glColor3f(0, 0, 0)
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
                vl.draw(gl.GL_TRIANGLES)
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
                vl.delete()
            except Exception:
                # If vertex_list_indexed isn't available in this Pyglet version fallback to older call
                # (most Pyglet installations have it; keep fallback to prevent crashes)
                gl.glColor3f(0, 0, 0)
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
                pyglet.graphics.draw(24, gl.GL_TRIANGLES, ('v3f/static', vertex_data))
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

    def draw_label(self):
        x, y, z = self.position
        self.label.text = '%02d (%.2f, %.2f, %.2f) %d / %d' % (
            pyglet.clock.get_fps(), x, y, z,
            len(self.model._shown), len(self.model.world)
        )
        self.label.draw()

    def draw_reticle(self):
        gl.glColor3f(0, 0, 0)
        if self.reticle:
            self.reticle.draw(gl.GL_LINES)


def setup():
    """Basic OpenGL configuration (no legacy fog)."""
    gl.glClearColor(0.5, 0.69, 1.0, 1.0)
    gl.glEnable(gl.GL_CULL_FACE)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)


def main():
    try:
        print("Starting Pyglet window...")
        window = Window(width=1280, height=720, caption='Minecraft', resizable=True)
        window.set_exclusive_mouse(True)
        setup()
        pyglet.app.run()
    except Exception:
        print("Fatal error in main:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
