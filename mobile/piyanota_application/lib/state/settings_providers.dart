import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../services/settings_prefs_service.dart';
import 'auth_providers.dart';

final settingsPrefsServiceProvider = Provider<SettingsPrefsService>(
  (ref) => SettingsPrefsService(),
);

/// PIYA-212 AC1: the signed-in address, read from the session saved at
/// Login/Sign-Up. Null when it isn't stored; Settings words that case.
final accountEmailProvider = FutureProvider.autoDispose<String?>(
  (ref) => ref.watch(sessionStorageProvider).readEmail(),
);

/// PIYA-212 AC2. "1.0.0 (1)": the build number tells two installs of the
/// same version apart when a tester reports a bug.
String formatAppVersion(String version, String buildNumber) =>
    buildNumber.isEmpty ? version : '$version ($buildNumber)';

final appVersionProvider = FutureProvider<String>(
  (ref) async {
    final info = await PackageInfo.fromPlatform();
    return formatAppVersion(info.version, info.buildNumber);
  },
  // The installed package can't change while the app runs, so Riverpod's
  // automatic retry would only delay showing "Unknown".
  retry: (_, _) => null,
);

/// Reads the Settings default tempo for a "Not sure" submit (PIYA-212 AC8).
/// A preferences failure must not block the upload: the server then keeps
/// its own default, which is what "Not sure" meant before Settings existed.
Future<int?> readFallbackTempo(SettingsPrefsService prefs) async {
  try {
    return await prefs.getDefaultTempo();
  } catch (e, stack) {
    debugPrint('Default tempo unreadable, sending none: $e\n$stack');
    return null;
  }
}
