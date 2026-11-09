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
///
/// [gradient] replaces the flat fill for a CTA drawn as a gradient (Export
/// Audio, PIYA-211); its stops follow the same disabled/pressed rules.
/// [loadingLabel] keeps a word next to the spinner when the wait is long
/// enough that a bare spinner reads as frozen.
class PrimaryPillButton extends StatelessWidget {
  const PrimaryPillButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.backgroundColor,
    this.foregroundColor = Colors.white,
    this.isLoading = false,
    this.gradient,
    this.loadingLabel,
    this.labelStyle,
  });

  final String label;
  final VoidCallback? onPressed;
  final Color? backgroundColor;
  final Color foregroundColor;
  final bool isLoading;
  final LinearGradient? gradient;
  final String? loadingLabel;

  /// Merged over the theme's labelLarge w600, e.g. to reach large-text
  /// size where a sampled fill only clears the 3:1 floor.
  final TextStyle? labelStyle;

  static const double _spinnerSize = 20;
  static const double _spinnerStroke = 2.5;
  // Disabled fill keeps the brand hue at reduced strength so the button
  // still reads as "the" CTA, just not yet actionable.
  static const double _disabledAlpha = 0.4;
  static const double _loadingGap = 12;

  @override
  Widget build(BuildContext context) {
    final baseColor = backgroundColor ?? AppTheme.primaryBlue;
    final gradient = this.gradient;
    final loadingLabel = this.loadingLabel;
    final textStyle = Theme.of(context).textTheme.labelLarge
        ?.copyWith(fontWeight: FontWeight.w600, color: foregroundColor)
        .merge(labelStyle);
    Color stop(Color c, Set<WidgetState> states) {
      if (isLoading) return c;
      if (states.contains(WidgetState.disabled)) {
        return c.withValues(alpha: _disabledAlpha);
      }
      if (states.contains(WidgetState.pressed)) return AppTheme.darken(c);
      return c;
    }

    return ElevatedButton(
      onPressed: isLoading ? null : onPressed,
      style: ButtonStyle(
        // A loading button stays full-strength: it's busy, not unavailable.
        backgroundColor: WidgetStateProperty.resolveWith(
          (states) => gradient == null
              ? stop(baseColor, states)
              // Clear, so a faded (disabled) gradient is not tinted by
              // the default fill underneath.
              : Colors.transparent,
        ),
        backgroundBuilder: gradient == null
            ? null
            : (context, states, child) => DecoratedBox(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(999),
                  gradient: LinearGradient(
                    begin: gradient.begin,
                    end: gradient.end,
                    colors: [for (final c in gradient.colors) stop(c, states)],
                    stops: gradient.stops,
                  ),
                ),
                child: child,
              ),
        foregroundColor: WidgetStatePropertyAll(foregroundColor),
        elevation: const WidgetStatePropertyAll(0),
        padding: const WidgetStatePropertyAll(
          EdgeInsets.symmetric(horizontal: 32, vertical: 16),
        ),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
        ),
        textStyle: WidgetStatePropertyAll(textStyle),
      ),
      child: !isLoading
          ? Text(label)
          : Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox.square(
                  dimension: _spinnerSize,
                  child: CircularProgressIndicator(
                    strokeWidth: _spinnerStroke,
                    color: foregroundColor,
                    // With a visible label, that label is what's announced.
                    semanticsLabel: loadingLabel == null
                        ? '$label in progress'
                        : null,
                  ),
                ),
                if (loadingLabel != null) ...[
                  const SizedBox(width: _loadingGap),
                  Flexible(child: Text(loadingLabel)),
                ],
              ],
            ),
    );
  }
}
