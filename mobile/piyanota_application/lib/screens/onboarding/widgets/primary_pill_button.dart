import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

/// Filled pill-shaped CTA used for "Next" / "Get Started". Darkens on press
/// per the project-wide press-state SOP (frontend-piyanota guide), rather
/// than relying on a generic opacity/ripple overlay.
class PrimaryPillButton extends StatelessWidget {
  const PrimaryPillButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.backgroundColor,
    this.foregroundColor = Colors.white,
  });

  final String label;
  final VoidCallback onPressed;
  final Color? backgroundColor;
  final Color foregroundColor;

  @override
  Widget build(BuildContext context) {
    final baseColor = backgroundColor ?? AppTheme.primaryBlue;

    return ElevatedButton(
      onPressed: onPressed,
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((states) {
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
      child: Text(label),
    );
  }
}
