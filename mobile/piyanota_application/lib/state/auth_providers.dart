import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';
import '../services/auth_api.dart';
import '../services/fake_auth_api.dart';
import '../services/session_storage.dart';

final dioProvider = Provider<Dio>((ref) {
  return Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      contentType: Headers.jsonContentType,
    ),
  );
});

/// Swapped to [FakeAuthApi] by default until the Module 3 API is deployed
/// (see [ApiConfig.useFakeAuth]). Fails loudly rather than letting requests
/// go to a relative URL if the real API is requested without a base URL.
final authApiProvider = Provider<AuthApi>((ref) {
  if (ApiConfig.useFakeAuth) return FakeAuthApi();
  if (ApiConfig.baseUrl.isEmpty) {
    throw StateError(
      'USE_FAKE_AUTH=false requires --dart-define=API_BASE_URL=<url>',
    );
  }
  return HttpAuthApi(ref.watch(dioProvider));
});

final sessionStorageProvider = Provider<SessionStorage>((ref) {
  return SessionStorage();
});
