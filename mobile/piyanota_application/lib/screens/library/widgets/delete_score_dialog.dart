import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../library_messages.dart';

/// PIYA-309 AC5: the API deletes without asking, so every delete path (the
/// library's trash and swipe, and the failure view's Delete, PIYA-218 AC3)
/// confirms with this first. Pops true on Delete.
class DeleteScoreDialog extends StatelessWidget {
  const DeleteScoreDialog({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: Colors.white,
      title: const Text(LibraryMessages.deleteDialogTitle),
      content: Text(LibraryMessages.deleteDialogBody(title)),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          style: TextButton.styleFrom(
            foregroundColor: AppTheme.libraryScoreSubtitle,
          ),
          child: const Text(LibraryMessages.deleteCancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: TextButton.styleFrom(foregroundColor: AppTheme.errorRed),
          child: const Text(LibraryMessages.deleteConfirm),
        ),
      ],
    );
  }
}
