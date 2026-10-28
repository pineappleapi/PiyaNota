import 'package:shared_preferences/shared_preferences.dart';

import 'backoff.dart';

const String _failuresKeyPrefix = 'login_throttle.failures.';
const String _untilKeyPrefix = 'login_throttle.until.';

/// Per-email wait after wrong passwords (PIYA-202-V2.1), kept in
/// shared_preferences so closing the app does not shorten it (AC4).
///
/// Kept per email, not per device, so mistyping one address does not lock
/// out the user's real account. The server enforces its own limit too (AC5);
/// this one only makes the wait visible and survivable offline.
class LoginThrottle {
  /// Time left before [email] may try again; zero when free to submit.
  Future<Duration> remaining(String email, {DateTime? now}) async {
    final prefs = await SharedPreferences.getInstance();
    final untilMs = prefs.getInt(_untilKeyPrefix + _key(email));
    if (untilMs == null) return Duration.zero;
    final left = DateTime.fromMillisecondsSinceEpoch(
      untilMs,
    ).difference(now ?? DateTime.now());
    return left.isNegative ? Duration.zero : left;
  }

  /// Counts one wrong password and starts the next, longer wait.
  Future<void> recordFailure(String email, {DateTime? now}) async {
    final prefs = await SharedPreferences.getInstance();
    final key = _key(email);
    final failures = (prefs.getInt(_failuresKeyPrefix + key) ?? 0) + 1;
    await prefs.setInt(_failuresKeyPrefix + key, failures);
    await _setUntil(prefs, key, backoffAfter(failures), now);
  }

  /// Shows the server's 429 wait instead of our own. The count is left
  /// alone: the server, not a wrong password seen here, caused this wait.
  Future<void> recordServerWait(
    String email,
    Duration wait, {
    DateTime? now,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await _setUntil(prefs, _key(email), wait, now);
  }

  /// Clears the count and the wait after a successful login (AC3).
  Future<void> reset(String email) async {
    final prefs = await SharedPreferences.getInstance();
    final key = _key(email);
    await prefs.remove(_failuresKeyPrefix + key);
    await prefs.remove(_untilKeyPrefix + key);
  }

  Future<void> _setUntil(
    SharedPreferences prefs,
    String key,
    Duration wait,
    DateTime? now,
  ) => prefs.setInt(
    _untilKeyPrefix + key,
    (now ?? DateTime.now()).add(wait).millisecondsSinceEpoch,
  );

  /// Same normalisation as the fake backend, so a differently-cased or
  /// padded address shares one count.
  String _key(String email) => email.trim().toLowerCase();
}
