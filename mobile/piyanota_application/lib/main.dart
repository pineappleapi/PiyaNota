import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import 'app.dart';
import 'config/api_config.dart';
import 'services/metronome_click.dart';

void main() {
  // Fail on launch, not on the first Log In tap, if the APK was built
  // without a usable backend (see ApiConfig.configurationError).
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);

  WidgetsFlutterBinding.ensureInitialized();
  // Click files a killed run left behind (the cache only grows otherwise).
  // A Flutter engine kept alive for a background scan does not run main
  // again, so this never races a Playback that is still open.
  unawaited(_clearStaleFiles());

  runApp(const ProviderScope(child: PiyaNotaApp()));
}

Future<void> _clearStaleFiles() async {
  try {
    await clearStaleClickTracks(await getTemporaryDirectory());
  } on Object catch (e) {
    debugPrint('Startup clean-up skipped: $e');
  }
}
