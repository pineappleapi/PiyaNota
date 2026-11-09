import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

/// "Don't have an account? Sign Up" line under the sheet title. A real
/// TextButton (not a tappable TextSpan) keeps a 48dp touch target.
class AuthSwitchPrompt extends StatelessWidget {
  const AuthSwitchPrompt({
    super.key,
    required this.prompt,
    required this.actionLabel,
    required this.onPressed,
  });

  final String prompt;
  final String actionLabel;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Wrap(
      alignment: WrapAlignment.center,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Text(
          prompt,
          style: textTheme.bodyMedium?.copyWith(color: AppTheme.authSubtitle),
        ),
        TextButton(
          onPressed: onPressed,
          style: TextButton.styleFrom(
            foregroundColor: AppTheme.primaryBlue,
            visualDensity: VisualDensity.compact,
            textStyle: textTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          child: Text(actionLabel),
        ),
      ],
    );
  }
}
