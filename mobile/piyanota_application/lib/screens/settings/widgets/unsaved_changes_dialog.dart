import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../settings_messages.dart';

enum UnsavedChoice { discard, save }

/// F6: asked when the user leaves Settings with unsaved changes. Discard
/// sits on the left with no fill; Save on the right in the theme's primary
/// colour. Null means the prompt was dismissed (tap outside, system back),
/// which keeps the user on Settings.
Future<UnsavedChoice?> confirmUnsavedChanges(BuildContext context) {
  return showDialog<UnsavedChoice>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      backgroundColor: AppTheme.settingsSurface,
      surfaceTintColor: Colors.transparent,
      title: const Text(SettingsMessages.unsavedTitle),
      content: const Text(SettingsMessages.unsavedBody),
      actions: [
        TextButton(
          onPressed: () =>
              Navigator.of(dialogContext).pop(UnsavedChoice.discard),
          style: TextButton.styleFrom(foregroundColor: AppTheme.settingsText),
          child: const Text(SettingsMessages.discard),
        ),
        FilledButton(
          onPressed: () => Navigator.of(dialogContext).pop(UnsavedChoice.save),
          child: const Text(SettingsMessages.save),
        ),
      ],
    ),
  );
}
