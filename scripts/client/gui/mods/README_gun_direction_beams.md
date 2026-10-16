# Experimental gun-direction beam mod

File: `scripts/client/gui/mods/mod_gun_direction_beams.py`

## Scope

Test-only prototype for training rooms/private test servers. It polls loaded vehicle entities, reads `appearance.gunMatrix`, casts a collision segment up to 600 m, and drives a `LaserSightMatrixProvider` attached through `BigWorld.Servo`.

## Lifecycle copied from the supplied terrain-circle mod

- `start()` is idempotent. Outside an arena, while the local player is dead, or outside an explicitly recognized test session, it removes visuals and checks again at the slower `CHECK_INTERVAL`; while alive in a recognized test battle it updates at `UPDATE_INTERVAL`.
- `PlayerAvatar.onEnterWorld` starts polling after calling the original method.
- `PlayerAvatar.onLeaveWorld` removes active beams before calling the original method.
- `stop()` cancels the scheduled callback and removes models/animators; `reset()` only clears current visuals, allowing polling to continue.
- Hook originals are saved on `PlayerAvatar` once to avoid wrapping wrappers repeatedly during module reload.

## Required setup

1. Put the script in `res_mods/<client-version>/scripts/client/gui/mods/` for a development client that loads `.py`; retail clients generally need a Python 2.7-compatible `.pyc`.
2. Set `BEAM_SEQUENCE` to a valid `AnimationSequence` resource from the installed game client. This script-only repository does not include a verified beam sequence asset/path. `BigWorld.Model('')` by itself does not render a visible beam.
3. Verify `_is_test_session()` against the target build. Arena type metadata differs across WoT versions; the prototype intentionally fails closed when it cannot identify a training/test session.
4. Test in a private training/test environment and inspect `python.log` for API errors.

## APIs not verified in a running client

- `BigWorld.entities.get(vehicle_id)` / `BigWorld.entity(vehicle_id)` and `arena.vehicles.keys()` availability/shape in the target client build.
- `arena.arenaType.name` / `.description` as a reliable way to identify a training/private test session.
- The `AnimationSequence.Loader` callback and per-model binding lifecycle in this client version.
- `BigWorld.wg_collideDynamicStatic(..., 128, vehicle.id, -1, 0)` is copied from the repository's `BlinkingLaserSight`, but collision flags/results should be checked in the target build.
- Whether the selected `AnimationSequence` produces a visible beam when bound to an empty `BigWorld.Model('')` model.
- `PlayerAvatar.onEnterWorld` / `onLeaveWorld` wrapping behavior should be verified against the exact client build.

This is an integration prototype, not a tested ready-to-use mod. `Vehicle.py`, `vehicle_extras.py`, and `LaserSightMatrixProvider` are used as references but were not modified.
