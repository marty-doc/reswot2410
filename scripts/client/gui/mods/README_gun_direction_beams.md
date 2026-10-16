# Experimental gun-direction beam mod

File: `scripts/client/gui/mods/mod_gun_direction_beams.py`

## Scope

Test-only prototype for training rooms/private test servers. It polls loaded vehicle entities, reads `appearance.gunMatrix`, casts a collision segment up to 564 m, and drives a `LaserSightMatrixProvider` attached through `BigWorld.Servo`.

## Required setup

1. Put the script in `res_mods/<client-version>/scripts/client/gui/mods/` for a development client that loads `.py`; retail clients generally need a Python 2.7-compatible `.pyc`.
2. Set `BEAM_SEQUENCE` in the script to a valid `AnimationSequence` resource from the installed game client. This script-only repository does not include a verified beam sequence asset/path. `BigWorld.Model('')` by itself does not render a visible beam.
3. Verify `_is_test_session()` against the target build. Arena type metadata differs across WoT versions; the prototype intentionally fails closed when it cannot identify a training/test session.
4. Test in a private training/test environment and inspect `python.log` for API errors.

## APIs not verified in a running client

- `BigWorld.entities.get(vehicle_id)` and `arena.vehicles.keys()` availability/shape in the target client build.
- `arena.arenaType.name` / `.description` as a reliable way to identify a training/private test session.
- The `AnimationSequence.Loader` callback and per-model binding lifecycle in this client version.
- `BigWorld.wg_collideDynamicStatic(..., 128, vehicle.id, -1, 0)` is copied from the repository's `BlinkingLaserSight`, but collision flags/results should be checked in the target build.
- Whether the selected `AnimationSequence` produces a visible beam when bound to an empty `BigWorld.Model('')` model.

This is an integration prototype, not a tested ready-to-use mod. No changes were made to `Vehicle.py`, `vehicle_extras.py`, or `LaserSightMatrixProvider`.
