import 'package:dio/dio.dart';

/// The wait a 429 `rate_limited` asks for, in seconds, or null when it
/// gives none. PIYA-101 AC9 / PIYA-102 AC9 / PIYA-322 AC5 send it twice;
/// the body's `error.retryAfterSeconds` wins over the `Retry-After`
/// header. Only the header's delta-seconds form is read: the contract
/// never sends an HTTP date, and a wrong guess is worse than the caller's
/// own default.
int? retryAfterSecondsOf(Response<dynamic>? response) {
  final body = response?.data;
  final error = body is Map<String, dynamic> ? body['error'] : null;
  final fromBody = error is Map<String, dynamic>
      ? error['retryAfterSeconds']
      : null;
  if (fromBody is int && fromBody >= 0) return fromBody;
  final header = int.tryParse(
    response?.headers.value('retry-after')?.trim() ?? '',
  );
  return header != null && header >= 0 ? header : null;
}
