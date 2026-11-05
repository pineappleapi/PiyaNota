import 'package:shared_preferences/shared_preferences.dart';

const String _untilKeyPrefix = 'login_throttle.until.';

/// Per-email wait deadline after wrong passwords (PIYA-202-V2.1), kept in
/// shared_preferences so closing the app does not shorten it (AC4).
///
/// Kept per email, not per device, so mistyping one address does not lock
/// out the user's real account. The server owns the ladder (J2); this only
/// stores the deadline it reports and never counts failures itself.
class LoginThrottle {
  /// [clock] exists so screen tests don't depend on the real time.
  LoginThrottle({DateTime Function()? clock}) : _clock = clock ?? DateTime.now;

  final DateTime Function() _clock;

  /// The throttle's notion of now, so a screen counting down agrees with
  /// the stored deadline.
  DateTime now() => _clock();

  /// Time left before [email] may try again; zero when free to submit.
  Future<Duration> remaining(String email, {DateTime? now}) async {
    final prefs = await SharedPreferences.getInstance();
    final untilMs = prefs.getInt(_untilKeyPrefix + _key(email));
    if (untilMs == null) return Duration.zero;
    final left = DateTime.fromMillisecondsSinceEpoch(untilMs)
        .difference(now ?? _clock());
    return left.isNegative ? Duration.zero : left;
  }

  /// Stores a wait the server reported (a 401 or 429 `retryAfterSeconds`).
  Future<void> recordServerWait(
    String email,
    Duration wait, {
    DateTime? now,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    await _setUntil(prefs, _key(email), wait, now);
  }

  /// Clears the wait after a successful login (AC3).
  Future<void> reset(String email) async {
    final prefs = await SharedPreferences.getInstance();
    final key = _key(email);
    await prefs.remove(_untilKeyPrefix + key);
  }

  Future<void> _setUntil(
    SharedPreferences prefs,
    String key,
    Duration wait,
    DateTime? now,
  ) => prefs.setInt(
    _untilKeyPrefix + key,
    (now ?? _clock()).add(wait).millisecondsSinceEpoch,
  );

  /// Same normalisation as the fake backend, so a differently-cased or
  /// padded address shares one count.
  String _key(String email) => email.trim().toLowerCase();
}
