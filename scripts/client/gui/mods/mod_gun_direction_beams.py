# -*- coding: utf-8 -*-
"""Experimental 3D gun-direction beams for local training/private test battles.

Install as scripts/client/gui/mods/mod_gun_direction_beams.py (development client)
OR compile with the client's Python 2.7 interpreter for retail .pyc loading.

IMPORTANT: set BEAM_SEQUENCE to a valid AnimationSequence resource from the
installed client. This repository contains the sequence API usage but does not
include the actual beam sequence asset/path. With an empty path the mod runs
without rendering and logs a warning rather than pretending the beam exists.
"""
from __future__ import absolute_import

import logging

import AnimationSequence
import BigWorld
import Math

from helpers.laser_sight_matrix_provider import LaserSightMatrixProvider

_LOG = logging.getLogger('gun_direction_beams')
_TAG = '[gun_direction_beams]'

# REQUIRED: point this at a real AnimationSequence resource in the game client.
# No valid path was discoverable in the script-only repository.
BEAM_SEQUENCE = ''
MAX_DISTANCE = 564.0
UPDATE_INTERVAL = 0.10
# Keep this test-only mod restricted to training/private test sessions.
ALLOW_ONLY_EXPLICIT_TEST_MODE = True

_timer_id = None
_beams = {}
_sequence_loader = None
_sequence = None
_sequence_ready = False
_warned_no_sequence = False


def init():
    global _timer_id, _sequence_loader, _sequence, _sequence_ready
    if not BEAM_SEQUENCE:
        _LOG.warning('%s BEAM_SEQUENCE is empty; collision/direction loop will run, but no visible beam can be rendered.', _TAG)
    else:
        try:
            player = BigWorld.player()
            _sequence_loader = AnimationSequence.Loader(BEAM_SEQUENCE, player.spaceID)
            _sequence = _sequence_loader.loadSync()
            BigWorld.loadResourceListBG((_sequence_loader,), _on_sequence_loaded)
        except Exception:
            _LOG.exception('%s failed to initialize beam sequence', _TAG)
    _timer_id = BigWorld.callback(1.0, _tick)
    _LOG.info('%s loaded (max distance %.0f m)', _TAG, MAX_DISTANCE)


def fini():
    global _timer_id, _sequence_loader, _sequence, _sequence_ready
    if _timer_id is not None:
        try:
            BigWorld.cancelCallback(_timer_id)
        except Exception:
            _LOG.exception('%s failed to cancel timer', _TAG)
        _timer_id = None
    for vehicle_id in list(_beams.keys()):
        _remove_beam(vehicle_id)
    _sequence = None
    _sequence_loader = None
    _sequence_ready = False
    _LOG.info('%s unloaded', _TAG)


def _on_sequence_loaded(resource_refs):
    global _sequence_ready
    try:
        failed_ids = getattr(resource_refs, 'failedIDs', ())
        if BEAM_SEQUENCE in failed_ids or _sequence is None:
            _LOG.error('%s sequence failed to load: %s', _TAG, BEAM_SEQUENCE)
            return
        _sequence_ready = True
        _LOG.info('%s sequence loaded: %s', _TAG, BEAM_SEQUENCE)
    except Exception:
        _LOG.exception('%s sequence load callback failed', _TAG)


def _is_test_session(player):
    """Conservative gate: inspect exposed arena/session metadata if available.

    WoT versions differ in arenaType names/flags. Unknown metadata fails closed;
    verify/adjust this gate for the target client build before use.
    """
    try:
        arena = player.arena
        arena_type = getattr(arena, 'arenaType', None)
        name = str(getattr(arena_type, 'name', '') or '').lower()
        description = str(getattr(arena_type, 'description', '') or '').lower()
        tokens = ('training', 'bootcamp', 'sandbox', 'test')
        return any(token in name or token in description for token in tokens)
    except Exception:
        return False


def _tick():
    global _timer_id
    _timer_id = None
    try:
        player = BigWorld.player()
        if player is None or getattr(player, 'arena', None) is None:
            _schedule_next()
            return
        if ALLOW_ONLY_EXPLICIT_TEST_MODE and not _is_test_session(player):
            _remove_all_beams()
            _schedule_next()
            return
        _update_vehicles(player)
    except Exception:
        _LOG.exception('%s update loop failed', _TAG)
    _schedule_next()


def _schedule_next():
    global _timer_id
    if _timer_id is None:
        _timer_id = BigWorld.callback(UPDATE_INTERVAL, _tick)


def _update_vehicles(player):
    arena = player.arena
    arena_vehicles = getattr(arena, 'vehicles', {})
    try:
        vehicle_ids = list(arena_vehicles.keys())
    except Exception:
        _LOG.debug('%s arena.vehicles is not a mapping in this client build', _TAG)
        return

    live_ids = set()
    entities = getattr(BigWorld, 'entities', {})
    for vehicle_id in vehicle_ids:
        try:
            vehicle = entities.get(vehicle_id)
            if vehicle is None or getattr(vehicle, 'model', None) is None:
                continue
            appearance = getattr(vehicle, 'appearance', None)
            gun_provider = getattr(appearance, 'gunMatrix', None) if appearance is not None else None
            if gun_provider is None:
                continue
            if getattr(vehicle, 'health', 1) <= 0:
                continue
            live_ids.add(vehicle_id)
            _update_one(player, vehicle_id, vehicle, gun_provider)
        except Exception:
            _LOG.debug('%s skipped vehicle %s', _TAG, vehicle_id, exc_info=True)

    for vehicle_id in list(_beams.keys()):
        if vehicle_id not in live_ids:
            _remove_beam(vehicle_id)


def _update_one(player, vehicle_id, vehicle, gun_provider):
    # CompoundAppearance.gunMatrix is a WGAdaptiveMatrixProvider. Vehicle.py
    # decodes packed gun angles into the vehicle filter; the appearance system
    # uses that state to update this provider.
    gun_matrix = Math.Matrix(gun_provider)
    start = gun_matrix.applyToOrigin()
    direction = gun_matrix.applyToAxis(2)
    end = start + direction * MAX_DISTANCE

    # Same collision API/signature used by vehicle_extras.BlinkingLaserSight.
    collision = BigWorld.wg_collideDynamicStatic(
        vehicle.spaceID, start, end, 128, vehicle.id, -1, 0)
    hit_point = collision[0] if collision is not None else end
    distance = start.distTo(hit_point)
    distance = max(0.0, min(MAX_DISTANCE, distance))

    beam = _beams.get(vehicle_id)
    if beam is None:
        beam = _create_beam(player, vehicle_id, gun_provider)
        if beam is None:
            return
        _beams[vehicle_id] = beam

    beam['matrix_provider'].beamMatrix = gun_provider
    beam['matrix_provider'].beamLength = distance
    beam['last_hit'] = hit_point


def _create_beam(player, vehicle_id, gun_provider):
    # The MatrixProduct/Servo pattern mirrors vehicle_extras.BlinkingLaserSight.
    try:
        matrix_provider = LaserSightMatrixProvider()
        matrix_provider.beamMatrix = gun_provider
        model = BigWorld.Model('')
        model.addMotor(BigWorld.Servo(matrix_provider.beamMatrix))
        player.addModel(model)
        beam = {'model': model, 'matrix_provider': matrix_provider,
                'animator': None, 'last_hit': None}

        # Empty model alone is invisible; the configured sequence is the
        # resource responsible for the actual beam geometry/effect.
        if _sequence_ready and _sequence is not None:
            animator = _sequence_loader.loadSync()
            animator.bindTo(AnimationSequence.ModelWrapperContainer(model, player.spaceID))
            animator.setEnabled(True)
            animator.start()
            beam['animator'] = animator
        return beam
    except Exception:
        _LOG.exception('%s could not create beam for vehicle %s', _TAG, vehicle_id)
        return None


def _remove_beam(vehicle_id):
    beam = _beams.pop(vehicle_id, None)
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


def _remove_all_beams():
    for vehicle_id in list(_beams.keys()):
        _remove_beam(vehicle_id)
