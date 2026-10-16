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
                self._ensure_sequence(player)
                self._update_vehicles(player)
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
        arena_vehicles = getattr(player.arena, 'vehicles', {})
        try:
            vehicle_ids = list(arena_vehicles.keys())
        except Exception:
            _LOG.debug('%s arena.vehicles is not a mapping in this client build')
            return

        live_ids = set()
        # BigWorld.entities is used as a mapping in some client builds; if this
        # build exposes only BigWorld.entity(id), the fallback below is tried.
        entities = getattr(BigWorld, 'entities', None)
        for vehicle_id in vehicle_ids:
            try:
                vehicle = None
                if entities is not None:
                    getter = getattr(entities, 'get', None)
                    if callable(getter):
                        vehicle = getter(vehicle_id)
                if vehicle is None:
                    vehicle = BigWorld.entity(vehicle_id)
                if vehicle is None or getattr(vehicle, 'model', None) is None:
                    continue
                if getattr(vehicle, 'health', 1) <= 0:
                    continue
                appearance = getattr(vehicle, 'appearance', None)
                gun_provider = getattr(appearance, 'gunMatrix', None) if appearance is not None else None
                if gun_provider is None:
                    continue
                if self._update_one(player, vehicle_id, vehicle, gun_provider):
                    live_ids.add(vehicle_id)
            except Exception:
                # Avoid leaving a stale beam at its previous coordinates.
                self._remove_beam(vehicle_id)
                _LOG.debug('%s skipped vehicle %s', _TAG, vehicle_id, exc_info=True)

        for vehicle_id in list(self._beams.keys()):
            if vehicle_id not in live_ids:
                self._remove_beam(vehicle_id)

    def _update_one(self, player, vehicle_id, vehicle, gun_provider):
        # Vehicle.py decodes packed gun angles; appearance.gunMatrix is expected
        # to expose the resulting world-space gun transform.
        try:
            gun_matrix = Math.Matrix(gun_provider)
            start = gun_matrix.applyToOrigin()
            direction = gun_matrix.applyToAxis(2)
            if start is None or direction is None:
                self._remove_beam(vehicle_id)
                return False
            end = start + direction * MAX_DISTANCE
        except Exception:
            self._remove_beam(vehicle_id)
            return False

        # Collision call/signature is copied from vehicle_extras.BlinkingLaserSight.
        collision = BigWorld.wg_collideDynamicStatic(
            vehicle.spaceID, start, end, 128, vehicle.id, -1, 0)
        hit_point = collision[0] if collision is not None else end
        distance = max(0.0, min(MAX_DISTANCE, start.distTo(hit_point)))

        beam = self._beams.get(vehicle_id)
        if beam is None:
            beam = self._create_beam(player, vehicle_id, gun_provider)
            if beam is None:
                return False
            self._beams[vehicle_id] = beam
        # If this beam was created before the .seq finished loading, attach it now.
        self._ensure_beam_animator(player, vehicle_id, beam)
        try:
            beam['matrix_provider'].beamMatrix = gun_provider
            # The stock training laser sequence is configured for a 10 m base length.
            beam['matrix_provider'].beamLength = distance / 10.0
            beam['last_hit'] = hit_point
            return True
        except Exception:
            self._remove_beam(vehicle_id)
            return False

    def _ensure_beam_animator(self, player, vehicle_id, beam):
        """Attach the sequence when it becomes ready, including for existing beams."""
        if beam.get('animator') is not None:
            return True
        if not self._sequence_ready or self._sequence_loader is None:
            return False
        try:
            animator = self._sequence_loader.loadSync()
            animator.bindTo(AnimationSequence.ModelWrapperContainer(
                beam['model'], player.spaceID))
            animator.setEnabled(True)
            animator.start()
            beam['animator'] = animator
            _LOG.info('%s animator started for vehicle %s (bound=%s, playing=%s)',
                      _TAG, vehicle_id, animator.isBound(), animator.isPlaying())
            return True
        except Exception:
            # Avoid flooding the log on every 50 ms update if the resource/client
            # build does not support this binding pattern.
            if not beam.get('animator_error_logged'):
                _LOG.exception('%s could not bind sequence for vehicle %s; '
                               'the beam model may remain invisible', _TAG, vehicle_id)
                beam['animator_error_logged'] = True
            return False

    def _create_beam(self, player, vehicle_id, gun_provider):
        try:
            matrix_provider = LaserSightMatrixProvider()
            matrix_provider.beamMatrix = gun_provider
            model = BigWorld.Model('')
            model.addMotor(BigWorld.Servo(matrix_provider.beamMatrix))
            player.addModel(model)
            beam = {'model': model, 'matrix_provider': matrix_provider,
                    'animator': None, 'last_hit': None,
                    'animator_error_logged': False}
            # Sequence loading is asynchronous. _update_one will retry attachment
            # after _sequence_ready becomes True, rather than leaving animator=None.
            self._ensure_beam_animator(player, vehicle_id, beam)
            return beam
        except Exception:
            _LOG.exception('%s could not create beam for vehicle %s', _TAG, vehicle_id)
            return None

    def _remove_beam(self, vehicle_id):
        beam = self._beams.pop(vehicle_id, None)
        if beam is None:
            return
        try:
            animator = beam.get('animator')
            if animator is not None:
                animator.stop()
                animator.setEnabled(False)
                animator.unbind()
        except Exception:
            _LOG.debug('%s animator cleanup failed for %s', _TAG, vehicle_id, exc_info=True)
        try:
            player = BigWorld.player()
            if player is not None and beam.get('model') is not None:
                player.delModel(beam['model'])
        except Exception:
            _LOG.debug('%s model cleanup failed for %s', _TAG, vehicle_id, exc_info=True)

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
