# -*- coding: utf-8 -*-
"""Experimental 3D gun-direction beams for local training/private test battles.

Install as scripts/client/gui/mods/mod_gun_direction_beams.py.
For retail WoT Python 2.7 clients, compile to .pyc if that client build does not
load .py mods. See README_gun_direction_beams.md for setup and API caveats.
"""
from __future__ import absolute_import

import logging

import AnimationSequence
import BigWorld
import Math
from Avatar import PlayerAvatar
from DebugDrawer import DebugDrawer

from helpers.laser_sight_matrix_provider import LaserSightMatrixProvider

_LOG = logging.getLogger('gun_direction_beams')
_TAG = '[gun_direction_beams]'

# REQUIRED: set this to a real AnimationSequence beam resource from the client.
# The script-only repository did not contain a verified beam resource path.
BEAM_SEQUENCE = 'particles/eff_sequence/maps_training_laser_e_staticBright_1.seq'
MAX_DISTANCE = 600.0
CHECK_INTERVAL = 0.1
UPDATE_INTERVAL = 0.05


class GunDirectionBeams(object):
    def __init__(self):
        self._running = False
        self._callback_id = None
        self._beams = {}
        self._sequence_loader = None
        self._sequence = None
        self._sequence_ready = False
        self._sequence_attempted = False
        self._player_space_id = None

    def start(self):
        """Start polling; drawing waits until the client is actually in battle."""
        if self._running:
            return
        self._running = True
        self._schedule(CHECK_INTERVAL)
        _LOG.info('%s started; waiting for arena (max %.0f m)', _TAG, MAX_DISTANCE)

    def reset(self):
        """Remove current visuals when leaving the world/arena."""
        self._deactivate()

    def stop(self):
        self._running = False
        if self._callback_id is not None:
            try:
                # BigWorld.cancel is used by the supplied working mod pattern.
                BigWorld.cancel(self._callback_id)
            except Exception:
                _LOG.debug('%s callback cancellation failed', _TAG, exc_info=True)
            self._callback_id = None
        self._deactivate()
        self._sequence_loader = None
        self._sequence = None
        self._sequence_ready = False
        self._sequence_attempted = False
        self._player_space_id = None
        _LOG.info('%s stopped', _TAG)

    def _schedule(self, delay):
        if not self._running or self._callback_id is not None:
            return
        try:
            self._callback_id = BigWorld.callback(delay, self._tick)
        except Exception:
            self._callback_id = None
            _LOG.exception('%s failed to schedule callback', _TAG)

    @staticmethod
    def _read_flag(obj, name):
        try:
            value = getattr(obj, name)
            if callable(value):
                value = value()
            return bool(value)
        except Exception:
            return None

    def _is_on_arena(self, player):
        if player is None:
            return False
        on_arena = self._read_flag(player, 'isOnArena')
        if on_arena is not None:
            return on_arena
        try:
            return bool(player.spaceID and player.playerVehicleID)
        except Exception:
            return False

    def _is_player_alive(self, player):
        """Return False when the local player is dead; unknown state is conservative."""
        alive = self._read_flag(player, 'isVehicleAlive')
        if alive is not None:
            return alive
        try:
            vehicle = getattr(player, 'vehicle', None)
            if vehicle is not None:
                health = getattr(vehicle, 'health', None)
                if health is not None:
                    return health > 0
        except Exception:
            pass
        try:
            vehicle_id = getattr(player, 'playerVehicleID', 0)
            vehicle = BigWorld.entity(vehicle_id) if vehicle_id else None
            if vehicle is not None:
                health = getattr(vehicle, 'health', None)
                if health is not None:
                    return health > 0
        except Exception:
            pass
        return False

    def _tick(self):
        self._callback_id = None
        if not self._running:
            return
        next_delay = CHECK_INTERVAL
        try:
            player = BigWorld.player()
            # Sleep between checks while outside battle or dead. No active visuals remain.
            if (player is None or not self._is_on_arena(player)
                    or not self._is_player_alive(player)):
                self._deactivate()
            else:
                self._update_vehicles(player)
                self._render_beams()
                next_delay = UPDATE_INTERVAL
        except Exception:
            _LOG.exception('%s update loop failed', _TAG)
            self._deactivate()
        if self._running:
            self._schedule(next_delay)

    def _ensure_sequence(self, player):
        if self._sequence_attempted:
            return
        self._sequence_attempted = True
        self._player_space_id = player.spaceID
        if not BEAM_SEQUENCE:
            _LOG.warning('%s BEAM_SEQUENCE is empty: polling works, but no visible beam resource is configured.', _TAG)
            return
        try:
            self._sequence_loader = AnimationSequence.Loader(BEAM_SEQUENCE, player.spaceID)
            self._sequence = self._sequence_loader.loadSync()
            BigWorld.loadResourceListBG((self._sequence_loader,), self._on_sequence_loaded)
        except Exception:
            _LOG.exception('%s failed to initialize beam sequence', _TAG)

    def _on_sequence_loaded(self, resource_refs):
        try:
            failed_ids = getattr(resource_refs, 'failedIDs', ())
            if BEAM_SEQUENCE in failed_ids or self._sequence is None:
                _LOG.error('%s sequence failed to load: %s', _TAG, BEAM_SEQUENCE)
                return
            self._sequence_ready = True
            _LOG.info('%s sequence loaded: %s', _TAG, BEAM_SEQUENCE)
        except Exception:
            _LOG.exception('%s sequence callback failed', _TAG)

    def _update_vehicles(self, player):
        # Draw only the local player's gun direction. This is a world-space
        # training/debug visualization, not an enemy gun-direction indicator.
        vehicle_id = getattr(player, 'playerVehicleID', 0)
        if not vehicle_id:
            self._deactivate()
            return

        try:
            vehicle = BigWorld.entity(vehicle_id)
            if vehicle is None or getattr(vehicle, 'model', None) is None:
                self._remove_beam(vehicle_id)
                return
            if getattr(vehicle, 'health', 1) <= 0:
                self._remove_beam(vehicle_id)
                return
            appearance = getattr(vehicle, 'appearance', None)
            gun_provider = getattr(appearance, 'gunMatrix', None) if appearance is not None else None
            if gun_provider is None:
                self._remove_beam(vehicle_id)
                return
            if not self._update_one(vehicle_id, vehicle, gun_provider):
                self._remove_beam(vehicle_id)
        except Exception:
            self._remove_beam(vehicle_id)
            _LOG.debug('%s skipped local vehicle %s', _TAG, vehicle_id, exc_info=True)

        for stale_id in list(self._beams.keys()):
            if stale_id != vehicle_id:
                self._remove_beam(stale_id)

    def _update_one(self, vehicle_id, vehicle, gun_provider):
        try:
            gun_matrix = Math.Matrix(gun_provider)
            start = gun_matrix.applyToOrigin()
            direction = gun_matrix.applyToAxis(2)
            if start is None or direction is None:
                return False
            end = start + direction * MAX_DISTANCE
        except Exception:
            return False

        # Match the stock laser's collision query so the line stops at the
        # first world collision instead of extending through terrain/vehicles.
        try:
            collision = BigWorld.wg_collideDynamicStatic(
                vehicle.spaceID, start, end, 128, vehicle.id, -1, 0)
            hit_point = collision[0] if collision is not None else end
        except Exception:
            hit_point = end

        beam = self._beams.get(vehicle_id)
        if beam is None:
            # Keep one logical line record per vehicle; only its endpoints move.
            beam = {'start': start, 'end': hit_point}
            self._beams[vehicle_id] = beam
        else:
            beam['start'] = start
            beam['end'] = hit_point
        return True

    def _render_beams(self):
        if not self._beams:
            return
        try:
            drawer = DebugDrawer()
            color = Math.Vector4(1.0, 0.15, 0.05, 1.0)
            for beam in self._beams.values():
                line = drawer.line()
                line.points([beam['start'], beam['end']])
                line.width(2.0)
                line.colour(color)
                line.zTest(False)
                line.zWrite(False)
        except Exception:
            _LOG.debug('%s DebugDrawer render failed', _TAG, exc_info=True)

    def _remove_beam(self, vehicle_id):
        self._beams.pop(vehicle_id, None)

    def _deactivate(self):
        for vehicle_id in list(self._beams.keys()):
            self._remove_beam(vehicle_id)


gun_direction_beams = GunDirectionBeams()

# Hook world lifecycle only once, so hot-reloading this module does not wrap the
# current wrappers repeatedly. This follows the supplied PlayerAvatar pattern.
if not hasattr(PlayerAvatar, '_gundir_original_on_enter_world'):
    PlayerAvatar._gundir_original_on_enter_world = PlayerAvatar.onEnterWorld
if not hasattr(PlayerAvatar, '_gundir_original_on_leave_world'):
    PlayerAvatar._gundir_original_on_leave_world = PlayerAvatar.onLeaveWorld


def _gundir_on_enter_world(self, prereqs):
    PlayerAvatar._gundir_original_on_enter_world(self, prereqs)
    gun_direction_beams.start()


def _gundir_on_leave_world(self):
    gun_direction_beams.reset()
    PlayerAvatar._gundir_original_on_leave_world(self)


PlayerAvatar.onEnterWorld = _gundir_on_enter_world
PlayerAvatar.onLeaveWorld = _gundir_on_leave_world

# Start at client startup; actual work waits for the player to enter an arena.
gun_direction_beams.start()
