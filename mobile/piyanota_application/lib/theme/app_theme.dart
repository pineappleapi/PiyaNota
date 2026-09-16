import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/voice_part.dart';

/// Central design tokens. Values marked "approximate" were read off Figma
/// screenshots by eye, not an exact eyedropper pick — swap for exact hex
/// once available (see .claude/agents/frontend-piyanota.md).
class AppTheme {
  AppTheme._();

  // Brand gradient — confirmed exact values (see PIYA-201 Figma export).
  static const Color gradientStart = Color(0xFF1B7DCE);
  static const Color gradientEnd = Color(0xFF01DCBA);

  static const LinearGradient primaryGradient = LinearGradient(
    begin: Alignment.bottomLeft,
    end: Alignment.topRight,
    colors: [gradientStart, gradientEnd],
  );

  static const Color primaryBlue = gradientStart;

  // Approximate — no dedicated dot color was sampled from Figma.
  static const Color dotActive = Color(0xFF1F2937);
  static const Color dotInactive = Color(0xFFD9D9D9);

  // Approximate voice-part accent colors, read by eye off the PIYA-201
  // voice-selection frame. Confirm/replace with exact hex once available.
  static const Map<VoicePart, ({Color background, Color icon})> voiceAccents =
      {
    VoicePart.soprano: (
      background: Color(0xFFF7DCE4),
      icon: Color(0xFFE0648A),
    ),
    VoicePart.alto: (
      background: Color(0xFFE3DEF6),
      icon: Color(0xFF8B7ED8),
    ),
    VoicePart.tenor: (
      background: Color(0xFFDBF2E3),
      icon: Color(0xFF4FAE7C),
    ),
    VoicePart.bass: (
      background: Color(0xFFDBEAF7),
      icon: Color(0xFF4A90D9),
    ),
  };

  /// Darkens [color] for a pressed-state SOP (see frontend-piyanota.md
  /// "Interaction states") — reduces HSL lightness rather than overlaying
  /// opacity, so the result stays the same hue, just deeper.
  static Color darken(Color color, [double amount = 0.12]) {
    final hsl = HSLColor.fromColor(color);
    final lightness = (hsl.lightness - amount).clamp(0.0, 1.0);
    return hsl.withLightness(lightness).toColor();
  }

  static ThemeData get light {
    final base = ThemeData(
      useMaterial3: true,
      // Explicit scheme per frontend-piyanota.md — this is a custom brand,
      // not a stock Material 3 seed-generated palette.
      colorScheme: const ColorScheme.light(
        primary: primaryBlue,
        onPrimary: Colors.white,
        secondary: gradientEnd,
        onSecondary: Colors.white,
        surface: Colors.white,
        onSurface: Color(0xFF1F2937),
        error: Color(0xFFB3261E),
        onError: Colors.white,
      ),
      scaffoldBackgroundColor: Colors.white,
    );

    return base.copyWith(
      textTheme: GoogleFonts.plusJakartaSansTextTheme(base.textTheme),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ButtonStyle(
          shape: WidgetStatePropertyAll(
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
          ),
          padding: const WidgetStatePropertyAll(
            EdgeInsets.symmetric(vertical: 16),
          ),
          backgroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.pressed)) {
              return darken(primaryBlue);
            }
            return primaryBlue;
          }),
          foregroundColor: const WidgetStatePropertyAll(Colors.white),
          textStyle: WidgetStatePropertyAll(
            GoogleFonts.plusJakartaSans(
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
    );
  }
}
