import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import 'processing_messages.dart';

/// PIYA-207 AC4's "Cancel scan?" confirmation, shared with the library
/// card's long-press (PIYA-218 AC4) so both ask the same way. True only
/// when the user confirmed.
Future<bool> confirmCancelScan(BuildContext context) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text(ProcessingMessages.cancelTitle),
      content: const Text(ProcessingMessages.cancelBody),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text(ProcessingMessages.keepScanning),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: TextButton.styleFrom(foregroundColor: AppTheme.errorRed),
          child: const Text(ProcessingMessages.confirmCancel),
        ),
      ],
    ),
  );
  return confirmed == true;
}
