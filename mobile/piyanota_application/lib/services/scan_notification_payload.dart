/// What a conversion-result notification carries: the job id and nothing else
/// (never a URL, token or title). One place builds and reads it, so the
/// foreground service and a future background isolate (Task 6) agree.
///
/// The payload is the id as a plain string, the same shape the native
/// notification already stores as its intent extra, so notifications posted by
/// an earlier build still parse. Anything that is not a plausible id (empty,
/// spaces, a URL, a JSON blob, over-long) reads as null: callers then open the
/// Library instead of guessing.
class ScanNotificationPayload {
  ScanNotificationPayload._();

  static const int maxLength = 128;
  static final RegExp _plausibleId = RegExp(r'^[A-Za-z0-9_-]{1,128}$');

  /// The payload for [jobId] (a String, or an int the backend may use), or
  /// null when the id could not be read back by [parse].
  static String? build(Object? jobId) => parse(jobId);

  /// The job id inside [payload] (a String or int), or null when malformed.
  static String? parse(Object? payload) {
    final text = switch (payload) {
      final String s => s.trim(),
      final int i when i >= 0 => '$i',
      _ => null,
    };
    return text != null && _plausibleId.hasMatch(text) ? text : null;
  }
}
