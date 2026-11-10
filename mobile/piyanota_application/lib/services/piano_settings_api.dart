import 'package:dio/dio.dart';

import '../config/api_config.dart';
import '../models/voice_part.dart';
import 'piano_octave.dart';
import 'session_storage.dart';

/// PIYA-321 body. [updatedAt] is null (and [isDefault] true) when the user
/// never saved an octave on the server.
class PianoSettings {
  const PianoSettings({
    required this.octave,
    required this.updatedAt,
    required this.isDefault,
  });

  final int octave;
  final DateTime? updatedAt;
  final bool isDefault;
}

sealed class PianoSettingsException implements Exception {
  const PianoSettingsException();
}

/// 401, or no stored token.
class PianoSettingsSessionExpiredException extends PianoSettingsException {
  const PianoSettingsSessionExpiredException();
}

/// No response: offline, DNS failure, timeout. Retry later.
class PianoSettingsNetworkException extends PianoSettingsException {
  const PianoSettingsNetworkException();
}

/// 400 `octave_*` / `client_updated_at_invalid` (AC 48): a client bug, never
/// retried.
class PianoSettingsRejectedException extends PianoSettingsException {
  const PianoSettingsRejectedException(this.code);
  final String code;
}

/// 5xx, an unexpected status, or a body the app can't use. Retry later.
class PianoSettingsServerException extends PianoSettingsException {
  const PianoSettingsServerException();
}

abstract interface class PianoSettingsApi {
  Future<PianoSettings> get(VoicePart? voice);

  /// [clientUpdatedAt] must be UTC; the server keeps the newer of the two
  /// values and returns the winner (PIYA-321 AC 7-8).
  Future<PianoSettings> put(
    int octave,
    DateTime clientUpdatedAt,
    VoicePart? voice,
  );
}

class HttpPianoSettingsApi implements PianoSettingsApi {
  HttpPianoSettingsApi(this._dio, this._sessionStorage);

  final Dio _dio;
  final SessionStorage _sessionStorage;

  @override
  Future<PianoSettings> get(VoicePart? voice) => _send(
    (options) => _dio.get<dynamic>(
      ApiConfig.pianoSettingsPath,
      queryParameters: {'voice': ?voice?.name},
      options: options,
    ),
  );

  @override
  Future<PianoSettings> put(
    int octave,
    DateTime clientUpdatedAt,
    VoicePart? voice,
  ) => _send(
    (options) => _dio.put<dynamic>(
      ApiConfig.pianoSettingsPath,
      // The server ignores voice on PUT, so none is sent.
      data: {
        'octave': octave,
        'clientUpdatedAt': clientUpdatedAt.toUtc().toIso8601String(),
      },
      options: options,
    ),
  );

  Future<PianoSettings> _send(
    Future<Response<dynamic>> Function(Options) call,
  ) async {
    final token = await _sessionStorage.readToken();
    if (token == null || token.isEmpty) {
      throw const PianoSettingsSessionExpiredException();
    }
    try {
      final response = await call(
        Options(headers: {'Authorization': 'Bearer $token'}),
      );
      return parse(response.data);
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  static PianoSettings parse(Object? body) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    final octave = data is Map<String, dynamic> ? data['octave'] : null;
    if (data is! Map<String, dynamic> || !isValidOctave(octave)) {
      throw const PianoSettingsServerException();
    }
    final at = data['updatedAt'];
    final parsed = at is String ? DateTime.tryParse(at)?.toUtc() : null;
    if (at != null && parsed == null) {
      throw const PianoSettingsServerException();
    }
    return PianoSettings(
      octave: octave as int,
      updatedAt: parsed,
      isDefault: data['isDefault'] == true,
    );
  }

  static PianoSettingsException mapDioError(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return const PianoSettingsNetworkException();
      case DioExceptionType.badResponse:
        final status = e.response?.statusCode;
        if (status == 401) return const PianoSettingsSessionExpiredException();
        if (status == 400) {
          final body = e.response?.data;
          final error = body is Map<String, dynamic> ? body['error'] : null;
          final code = error is Map<String, dynamic> ? error['code'] : null;
          final message = body is Map<String, dynamic> ? body['message'] : null;
          return PianoSettingsRejectedException('${code ?? message}');
        }
        return const PianoSettingsServerException();
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return const PianoSettingsServerException();
    }
  }
}

/// In-memory stand-in for PIYA-321 until Module 3 ships it: same
/// newer-timestamp-wins rule as the server (AC 7-8). Set [failure] to make
/// every call throw.
class FakePianoSettingsApi implements PianoSettingsApi {
  FakePianoSettingsApi({this.octave, this.updatedAt});

  int? octave;
  DateTime? updatedAt;
  PianoSettingsException? failure;
  int getCalls = 0;
  final List<({int octave, DateTime at, VoicePart? voice})> puts = [];

  PianoSettings _current(VoicePart? voice) => PianoSettings(
    octave: octave ?? defaultOctaveFor(voice),
    updatedAt: updatedAt,
    isDefault: updatedAt == null,
  );

  @override
  Future<PianoSettings> get(VoicePart? voice) async {
    getCalls++;
    if (failure != null) throw failure!;
    return _current(voice);
  }

  @override
  Future<PianoSettings> put(
    int octave,
    DateTime clientUpdatedAt,
    VoicePart? voice,
  ) async {
    puts.add((octave: octave, at: clientUpdatedAt, voice: voice));
    if (failure != null) throw failure!;
    final stored = updatedAt;
    if (stored == null || !clientUpdatedAt.isBefore(stored)) {
      this.octave = octave;
      updatedAt = clientUpdatedAt;
    }
    return _current(voice);
  }
}
