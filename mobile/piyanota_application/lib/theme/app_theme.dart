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

  // Dropper-sampled from references/PIYA201_Onboarding_Steps.png (2026-09-19).
  static const Color dotActive = Color(0xFF1F2937);
  static const Color dotInactive = Color(0xFFC4C4C4);

  // Onboarding-guide (PIYA-201) text/button tokens, dropper-sampled from
  // references/PIYA201_Onboarding_Steps.png. Distinct from primaryBlue: the
  // reference's onboarding CTA is measurably brighter than the brand blue
  // used elsewhere.
  static const Color onboardingHeadingDark = Color(0xFF272727);
  static const Color onboardingBody = Color(0xFF717171);
  static const Color onboardingSkipText = Color(0xFF8F8F8F);
  static const Color onboardingButtonBlue = Color(0xFF38A3D5);

  // Flat approximation of the teal->blue gradient the reference uses on
  // accent heading text. A full-line accent (e.g. step 1/2's second heading
  // line) renders with the real primaryGradient via ShaderMask instead; this
  // flat token only covers partial-line accents (e.g. just the word "sing"
  // mid-sentence), where shading part of a single text run isn't practical.
  static const Color onboardingAccent = Color(0xFF109DB8);

  // Workflow step (PIYA-201 step 2) tile fills, dropper-sampled.
  static const Color workflowTileCapture = Color(0xFF52DDD1);
  static const Color workflowTileWait = Color(0xFF3BB9CF);
  static const Color workflowTileListen = Color(0xFF5FB7DA);

  // Voice-selection card badge colors, dropper-sampled off the PIYA-201
  // voice-selection frame. Each badge is a solid pastel circle with a flat
  // white mic icon on top — unlike the old design, the color no longer needs
  // a separate darker "icon" tone.
  static const Map<VoicePart, Color> voiceAccents = {
    VoicePart.soprano: Color(0xFFF1BDCE),
    VoicePart.alto: Color(0xFFD0BFE4),
    VoicePart.tenor: Color(0xFFBFEEBF),
    VoicePart.bass: Color(0xFFB6D5EC),
  };

  // Auth screens (PIYA-202/203) neutrals, dropper-sampled from
  // references/PIYA202-LogIn_SignUp_Inspo.webp (2026-10-07). Only the
  // reference's neutrals are taken — its teal accents are replaced by the
  // brand gradient/blue so auth matches onboarding.
  static const Color authFieldFill = Color(0xFFF8F8F8);
  static const Color authHintText = Color(0xFF8F8F8F);
  static const Color authSubtitle = Color(0xFF7D7D7D);
  static const Color authFieldIcon = Color(0xFF7F7F7F);
  static const Color errorRed = Color(0xFFB3261E);
  static const Color errorBannerFill = Color(0xFFFDECEA);

  // Same brand stops as primaryGradient, reoriented top-left -> bottom-right
  // so the auth headline (top-left) sits on the blue end. White on the
  // gradient's teal midpoint falls below the 3:1 large-text contrast floor.
  static const LinearGradient authHeaderGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [gradientStart, gradientEnd],
  );

  // Derived (not sampled): a light tint of gradientEnd for the second
  // headline line, standing in for the reference's lighter accent words.
  static final Color authHeadlineAccent = Color.lerp(
    gradientEnd,
    Colors.white,
    0.55,
  )!;

  // Derived (not sampled — the auth reference has no success state): the
  // non-error counterpart of errorBannerFill, a pale primaryBlue tint so
  // confirmations (PIYA-204 AC2/AC5) read as brand, not as alarm. Body text
  // on it uses onboardingHeadingDark for contrast.
  static final Color noticeBannerFill = Color.lerp(
    primaryBlue,
    Colors.white,
    0.9,
  )!;

  // Score Library (PIYA-205), dropper-sampled from
  // references/PIYA203_Home Page_ListScores.png / _NewScores.png
  // (2026-10-08). The mockup's header and nav gradients are vertical and use
  // their own stops — measurably not primaryGradient's #1B7DCE/#01DCBA — so
  // they get separate tokens rather than reusing the brand pair.
  //
  // Darkened for AA, user decision 2026-10-08 (same hue, lower HSL
  // lightness, the smallest step that passes; the sampled value is kept in
  // each comment). White text must reach 4.5:1 (3:1 for the 34 sp title)
  // wherever it sits on a gradient, for any status-bar inset and text
  // scale; the subtitle and the search text land near the bottom stop, so
  // both header stops had to move.
  // Sampled #05CDBD (white 2.0:1). Now white 4.5:1.
  static const Color libraryHeaderTop = Color(0xFF03857B);
  // Sampled #178BCB (white 3.8:1). Now white 4.5:1.
  static const Color libraryHeaderBottom = Color(0xFF157DB7);
  static const LinearGradient libraryHeaderGradient = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [libraryHeaderTop, libraryHeaderBottom],
  );
  // Darkened for AA, user decision 2026-10-08: both stops lowered by the
  // same lightness step so the 13 sp white labels (lower half of the bar)
  // reach 4.5:1 for any bottom inset. Sampled #168ECA / #0BB9C2.
  static const Color libraryNavTop = Color(0xFF106A97);
  static const Color libraryNavBottom = Color(0xFF08868D);
  static const LinearGradient libraryNavGradient = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [libraryNavTop, libraryNavBottom],
  );
  static const Color libraryBackground = Color(0xFFE8E8E8);
  static const Color libraryCardOutline = Color(0xFF8D8585);
  static const Color libraryScoreCardFill = Color(0xFFC2DFEF);
  static const Color libraryAddTileFill = Color(0xFFD9EAF3);
  static const Color libraryIconBlue = Color(0xFF1894D5);
  static const Color libraryCardTitle = Color(0xFF3D3D3D);
  // Darkest anti-aliased pixel of each subtitle — small text never renders a
  // fully solid pixel, so this is the closest sample to the source colour.
  // Darkened for AA, user decision 2026-10-08: sampled #8D8585 (3.6:1 on
  // the white card), now 4.6:1.
  static const Color libraryAddSubtitle = Color(0xFF7C7474);
  static const Color libraryScoreSubtitle = Color(0xFF575757);
  // Darkened for AA, user decision 2026-10-08: sampled #4B8CAD (2.7:1 on
  // libraryScoreCardFill), now 3.0:1, the non-text minimum.
  static const Color libraryTrash = Color(0xFF4683A2);
  // Search field: no fill (inside == surrounding gradient pixels); border and
  // hint are white at the alpha that reproduces the sampled #89CAE4 / #D0EAF4
  // over the header blue.
  static const double librarySearchBorderAlpha = 0.5;
  static const double librarySearchHintAlpha = 0.8;
  // Capture button halo: the grey above the button deepens from #E2E2E2 to
  // #D0D0D0 at its edge, i.e. ~10% black at the rim of a soft blur.
  static const Color libraryCaptureShadow = Color(0x33000000);
  // Round-2 polish (PIYA-205, 2026-10-08). Not in the mockups, so these are
  // derived from the sampled colours above rather than dropper-sampled:
  // - Header logo: the full-colour PNG at reduced opacity (user asked for it
  //   faded, not flat white like the auth watermark), top-right.
  static const double libraryHeaderLogoOpacity = 0.4;
  // - Selected bottom-nav tab: a white pill behind the icon at this alpha,
  //   visible on both nav gradient stops without competing with the labels.
  static const double libraryNavIndicatorAlpha = 0.22;
  // - Skeleton shimmer: the static bar is white at the base alpha; a band at
  //   the highlight alpha sweeps across it.
  static const double librarySkeletonBaseAlpha = 0.7;
  static const double librarySkeletonHighlightAlpha = 0.95;

  // Capture / Add Score (PIYA-206), dropper-sampled from
  // references/PIYA206_CaptureScreen_MultipleImage.png (2026-10-08).
  // Unlike the library header these stops are kept as sampled: everything
  // on the gradient is navy (captureInk), which passes 4.5:1 down to the
  // bottom stop (4.57:1); the mockup's white text would not (3.8:1), so no
  // white text is placed on it.
  // Sampled #05CEBD (navy 8.2:1).
  static const Color captureBackgroundTop = Color(0xFF05CEBD);
  // Sampled #178BCB (navy 4.57:1).
  static const Color captureBackgroundBottom = Color(0xFF178BCB);
  static const LinearGradient captureBackgroundGradient = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [captureBackgroundTop, captureBackgroundBottom],
  );
  // Title text, camera frame fill, page labels, button text. Sampled #091D2C.
  static const Color captureInk = Color(0xFF091D2C);
  // ✕ button fill; white ✕ on it is 3.3:1 (icon, 3:1 floor). Sampled
  // #0F9F95.
  static const Color captureCloseFill = Color(0xFF0F9F95);
  // Corner brackets, thumbnail border, page action icons, submit fill.
  // Sampled #98FFF8 (on captureInk 14.7:1).
  static const Color captureAccent = Color(0xFF98FFF8);
  // Frame placeholder art when the camera isn't live. Decorative. Sampled
  // #2C4652.
  static const Color capturePlaceholderGlyph = Color(0xFF2C4652);
  // Thumbnail placeholder art. Decorative. Sampled #97C3C6.
  static const Color captureThumbGlyph = Color(0xFF97C3C6);
  // Adjusted for AA, 2026-10-08: the mockup's dotted "+" tile has no fill,
  // and its cyan plus on the gradient is 2.7:1 (3:1 floor). A captureInk
  // fill at this alpha lifts the plus to at least 3.35:1 on any part of
  // the gradient (4.7:1 where the strip actually sits).
  static const double captureAddTileFillAlpha = 0.35;
  // Derived (not in the mockup): a page thumbnail's ✎ and 🗑 sit on a solid
  // captureInk disc so the cyan icon keeps 14.7:1 over white paper (cyan on
  // white is 1.1:1). The mockup's trash sits on its dark placeholder art.

  // Processing (PIYA-207), dropper-sampled from
  // references/PIYA207_ProcessingScreen_{1,2,3}.png (2026-10-08).
  // User decision 2026-10-08: kept as sampled despite white-text AA
  // shortfall (~2:1 on the teal top). The card's stops differ from
  // captureBackgroundTop/Bottom by one unit in the top stop's green, a
  // sampling difference, so the capture gradient is reused.
  static const Color processingCardTop = captureBackgroundTop;
  static const Color processingCardBottom = captureBackgroundBottom;
  static const LinearGradient processingCardGradient =
      captureBackgroundGradient;
  // Unfilled progress track. Sampled #125178.
  static const Color processingTrack = Color(0xFF125178);
  // "page 2/3". Sampled #99F7F5.
  static const Color processingPageText = Color(0xFF99F7F5);
  // "✕ Cancel Scan". Sampled #DF5757 (3.7:1 on white; 18 sp bold counts
  // as large text, 3:1 floor).
  static const Color processingCancel = Color(0xFFDF5757);
  // Derived (not in the mockup): "Convert in Background" outline and text.
  // libraryHeaderBottom is 4.52:1 on white; the brand blue #1B7DCE (4.3:1)
  // would fail at this size.
  static const Color processingSecondary = libraryHeaderBottom;

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
        error: errorRed,
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
