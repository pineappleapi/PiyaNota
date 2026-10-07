import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Filled pill-shaped CTA used for "Next" / "Get Started" / "Log In". Darkens
/// on press per the project-wide press-state SOP (frontend-piyanota guide),
/// rather than relying on a generic opacity/ripple overlay.
///
/// A null [onPressed] renders the disabled state (e.g. PIYA-202 AC1: Log In
/// disabled until fields are filled). [isLoading] swaps the label for a
/// spinner and also blocks taps, so a request can't be double-submitted
/// (PIYA-202 AC6) even if the caller forgets to null [onPressed].
class PrimaryPillButton extends StatelessWidget {
  const PrimaryPillButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.backgroundColor,
    this.foregroundColor = Colors.white,
    this.isLoading = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final Color? backgroundColor;
  final Color foregroundColor;
  final bool isLoading;

  static const double _spinnerSize = 20;
  static const double _spinnerStroke = 2.5;
  // Disabled fill keeps the brand hue at reduced strength so the button
  // still reads as "the" CTA, just not yet actionable.
  static const double _disabledAlpha = 0.4;

  @override
  Widget build(BuildContext context) {
    final baseColor = backgroundColor ?? AppTheme.primaryBlue;

    return ElevatedButton(
      onPressed: isLoading ? null : onPressed,
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((states) {
          // A loading button stays full-strength: it's busy, not unavailable.
          if (isLoading) return baseColor;
          if (states.contains(WidgetState.disabled)) {
            return baseColor.withValues(alpha: _disabledAlpha);
          }
          if (states.contains(WidgetState.pressed)) {
            return AppTheme.darken(baseColor);
          }
          return baseColor;
        }),
        foregroundColor: WidgetStatePropertyAll(foregroundColor),
        elevation: const WidgetStatePropertyAll(0),
        padding: const WidgetStatePropertyAll(
          EdgeInsets.symmetric(horizontal: 32, vertical: 16),
        ),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
        ),
        textStyle: WidgetStatePropertyAll(
          Theme.of(context).textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w600,
                color: foregroundColor,
              ),
        ),
      ),
      child: isLoading
          ? SizedBox.square(
              dimension: _spinnerSize,
              child: CircularProgressIndicator(
                strokeWidth: _spinnerStroke,
                color: foregroundColor,
                semanticsLabel: '$label in progress',
              ),
            )
          : Text(label),
    );
  }
}
