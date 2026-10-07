import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'config/api_config.dart';

void main() {
  // Fail on launch, not on the first Log In tap, if the APK was built
  // without a usable backend (see ApiConfig.configurationError).
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);

  runApp(const ProviderScope(child: PiyaNotaApp()));
}
