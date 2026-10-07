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
/// (see [ApiConfig.useFakeAuth]). Re-checks the startup validation so the
/// provider can never hand out a client aimed at a relative or cleartext URL.
final authApiProvider = Provider<AuthApi>((ref) {
  if (ApiConfig.useFakeAuth) return FakeAuthApi();
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);
  return HttpAuthApi(ref.watch(dioProvider));
});

final sessionStorageProvider = Provider<SessionStorage>((ref) {
  return SessionStorage();
});
