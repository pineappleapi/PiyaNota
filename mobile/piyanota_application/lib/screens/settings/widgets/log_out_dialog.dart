import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../settings_messages.dart';

/// PIYA-212 AC4: the confirmation step before Log out. True only on an
/// explicit "Log out"; Cancel, Back and a tap outside all keep the session.
Future<bool> confirmLogOut(BuildContext context) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      backgroundColor: AppTheme.settingsSurface,
      surfaceTintColor: Colors.transparent,
      title: const Text(SettingsMessages.logOutTitle),
      content: const Text(SettingsMessages.logOutBody),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(false),
          style: TextButton.styleFrom(foregroundColor: AppTheme.settingsText),
          child: const Text(SettingsMessages.cancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(true),
          style: TextButton.styleFrom(
            foregroundColor: AppTheme.settingsLogOut,
            textStyle: const TextStyle(fontWeight: FontWeight.w700),
          ),
          child: const Text(SettingsMessages.logOut),
        ),
      ],
    ),
  );
  return confirmed ?? false;
}
