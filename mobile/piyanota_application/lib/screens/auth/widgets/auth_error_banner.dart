import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

/// Inline request-failure message (PIYA-202 AC2/AC7, PIYA-203 AC5). Shown
/// in-page rather than as a SnackBar so it stays visible next to the form
/// while the user corrects their input. Announced as a live region so
/// TalkBack reads it without the user hunting for it.
class AuthErrorBanner extends StatelessWidget {
  const AuthErrorBanner({
    super.key,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  static const EdgeInsets _padding = EdgeInsets.fromLTRB(16, 12, 16, 12);
  static const double _radius = 16;
  static const double _iconGap = 12;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final action = actionLabel;

    return Semantics(
      liveRegion: true,
      container: true,
      child: Container(
        padding: _padding,
        decoration: BoxDecoration(
          color: AppTheme.errorBannerFill,
          borderRadius: BorderRadius.circular(_radius),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.error_outline_rounded, color: AppTheme.errorRed),
            const SizedBox(width: _iconGap),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    message,
                    style: textTheme.bodyMedium?.copyWith(
                      color: AppTheme.errorRed,
                    ),
                  ),
                  if (action != null)
                    TextButton(
                      onPressed: onAction,
                      style: TextButton.styleFrom(
                        padding: EdgeInsets.zero,
                        foregroundColor: AppTheme.primaryBlue,
                        textStyle: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      child: Text(action),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
