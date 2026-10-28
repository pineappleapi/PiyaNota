import 'dart:math' as math;

/// Wait after the first counted failure. Short enough not to punish a typo,
/// long enough that guessing at it is not worth anyone's time.
const Duration _firstWait = Duration(seconds: 30);

/// Ceiling so a locked-out user is never told to wait longer than this.
const Duration _maxWait = Duration(minutes: 15);

/// 30 s doubled five times is 960 s, already past [_maxWait]; clamping the
/// exponent here keeps the shift from overflowing for any failure count.
const int _maxDoublings = 5;

/// Wait after [failures] counted failures: 30 s, doubling, capped at 15 min.
/// 0 → Duration.zero.
///
/// Shared by the login throttle and the reset-code wait so both screens
/// back off on the same schedule.
Duration backoffAfter(int failures) {
  if (failures <= 0) return Duration.zero;
  final doublings = math.min(failures - 1, _maxDoublings);
  final wait = _firstWait * (1 << doublings);
  return wait > _maxWait ? _maxWait : wait;
}
