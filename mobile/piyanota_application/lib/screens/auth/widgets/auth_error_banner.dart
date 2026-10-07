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

  @override
  Widget build(BuildContext context) {
    return _AuthBanner(
      message: message,
      icon: Icons.error_outline_rounded,
      iconColor: AppTheme.errorRed,
      textColor: AppTheme.errorRed,
      fill: AppTheme.errorBannerFill,
      actionLabel: actionLabel,
      onAction: onAction,
    );
  }
}

/// Non-error counterpart of [AuthErrorBanner] — same shape and live-region
/// behaviour, brand-tinted — for confirmations such as "reset code sent"
/// (PIYA-204 AC2) or "password reset" on Login (PIYA-204 AC5). Kept a
/// separate widget so a success can never be styled as a failure by a
/// mistyped flag.
class AuthNoticeBanner extends StatelessWidget {
  const AuthNoticeBanner({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return _AuthBanner(
      message: message,
      icon: Icons.check_circle_outline_rounded,
      iconColor: AppTheme.primaryBlue,
      textColor: AppTheme.onboardingHeadingDark,
      fill: AppTheme.noticeBannerFill,
    );
  }
}

class _AuthBanner extends StatelessWidget {
  const _AuthBanner({
    required this.message,
    required this.icon,
    required this.iconColor,
    required this.textColor,
    required this.fill,
    this.actionLabel,
    this.onAction,
  });

  final String message;
  final IconData icon;
  final Color iconColor;
  final Color textColor;
  final Color fill;
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
          color: fill,
          borderRadius: BorderRadius.circular(_radius),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: iconColor),
            const SizedBox(width: _iconGap),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    message,
                    style: textTheme.bodyMedium?.copyWith(color: textColor),
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
