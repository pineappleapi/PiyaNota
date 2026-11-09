import 'package:flutter/material.dart';

import '../services/notification_permission.dart';

/// Explains, then shows Android 13+'s notification prompt on Allow; once
/// per install, whatever the answer (user decision 2026-10-22). Shared by
/// the first export (PIYA-211) and "Convert in Background" (PIYA-218),
/// each with its own words; whichever comes first asks.
Future<void> askForNotificationsOnce(
  BuildContext context,
  NotificationPermission permission, {
  required String title,
  required String body,
  required String later,
  required String allow,
}) async {
  if (!await permission.shouldAsk() || !context.mounted) return;
  await permission.markAsked();
  if (!context.mounted) return;
  final allowed = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(later),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: Text(allow),
        ),
      ],
    ),
  );
  if (allowed ?? false) await permission.request();
}
