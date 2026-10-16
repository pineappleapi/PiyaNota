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

  // Playback (PIYA-208), dropper-sampled from
  // references/PIYA208_ScorePlayback UI.png (2026-10-09).
  // Back/download discs and the play glyph. Sampled #272960 (white icon on
  // it 13.4:1; on playbackPlayFill 11.4:1).
  static const Color playbackNavy = Color(0xFF272960);
  // Title. Sampled #3D3D3D, same as the library card title (10.9:1).
  static const Color playbackTitle = libraryCardTitle;
  // Adjusted for AA, 2026-10-09: "arr. by …" and "Select voice/s to hear."
  // sampled #898989 is 3.5:1 on white; HSL lightness −0.075, the smallest
  // 0.005 step that reaches 4.5:1, gives #767676 (4.54:1).
  static const Color playbackSubtle = Color(0xFF767676);
  // Unselected chip fill. Sampled #D7E4E9.
  static const Color playbackChipFill = Color(0xFFD7E4E9);
  // Adjusted for AA, 2026-10-09: chip text sampled #7993A5 is 2.5:1 on the
  // chip fill; HSL lightness −0.17 (smallest 0.005 step) gives #506777
  // (4.56:1 on the fill).
  static const Color playbackChipText = Color(0xFF506777);
  // Derived (no selected chip in the mockup): the unselected text colour as
  // the fill, so both states come from one sampled family. White text and
  // check on it 5.9:1.
  static const Color playbackChipSelectedFill = playbackChipText;
  // Indicator band. The mockup's band is an opaque #CDE7F5 behind the notes;
  // this blue at ~30% alpha composites to exactly #CDE7F5 over white paper
  // while black notes under it stay at ~10:1, so it can sit on top of the
  // image.
  static const Color playbackBand = Color(0x4D58AFDE);
  // Bottom panel gradient. Sampled #019EB0 → #116490. White text on it is
  // 3.2:1 at the very top but ≥4.85:1 from 60% down, where the times and
  // the Voice Mixer/Speed labels sit (≥5.0:1 there); the cyan skip icons sit
  // ~20% down at ≥3.16:1 (icons, 3:1 floor).
  static const Color playbackPanelTop = Color(0xFF019EB0);
  static const Color playbackPanelBottom = Color(0xFF116490);
  static const LinearGradient playbackPanelGradient = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [playbackPanelTop, playbackPanelBottom],
  );
  // Play disc and skip icons. Sampled #98FFF8 (= captureAccent).
  static const Color playbackAccent = captureAccent;
  // Derived (not in the mockup): the review banner. Dark amber on pale
  // amber, 8.4:1, so it reads as a caution, not an error (errorRed).
  static const Color playbackReviewFill = Color(0xFFFFF4D6);
  static const Color playbackReviewText = Color(0xFF5C4400);

  // Voice Mixer (PIYA-209) and Speed (PIYA-210) sheets, dropper-sampled
  // from references/PIYA209_VoiceMixerModal_UI.png and
  // PIYA210_PlaybackSpeedModal_UI.png (2026-10-09). Contrast is on the
  // sheet's white unless noted.
  // Scrim over Playback. Not one flat pixel: solved from pixels sampled
  // under it and the same pixels on PIYA-208 (white #FFFFFF reads #8B98A5,
  // navy #272960 reads #1F2D55), which both fit #17314B at 50% alpha.
  static const Color sheetScrim = Color(0x8017314B);
  // Drag handle. Sampled #0A9BBD (3.26:1; a graphic, 3:1 floor).
  static const Color sheetHandle = Color(0xFF0A9BBD);
  // Titles, "Metronome Click", "Playback Speed" and the BPM value. Sampled
  // #383838 (11.73:1).
  static const Color sheetText = Color(0xFF383838);
  // Adjusted for AA, 2026-10-09: the subtitles sampled #898989 (3.5:1), the
  // same grey as Playback's, so the same fix: playbackSubtle #767676
  // (4.54:1).
  static const Color sheetSubtle = playbackSubtle;
  // Adjusted for AA, 2026-10-09: close X sampled #A9A9A9 is 2.35:1; HSL
  // lightness −0.085 (smallest 0.005 step to the 3:1 icon floor) gives
  // #939393 (3.07:1).
  static const Color sheetClose = Color(0xFF939393);
  // Row dividers. Sampled #E8E8E8 (decorative, no floor).
  static const Color sheetDivider = Color(0xFFE8E8E8);
  // Solo / Metronome checkbox. Sampled fill #D9D9D9 is only 1.41:1, under
  // the 3:1 a control's outline needs, so the fill is kept and a derived
  // border is added: the fill at HSL lightness −0.27, #949494 (3.03:1).
  static const Color sheetCheckFill = Color(0xFFD9D9D9);
  static const Color sheetCheckBorder = Color(0xFF949494);
  // Derived (no ticked box in the mockups): navy fill, white tick (13.36:1).
  static const Color sheetCheckOn = playbackNavy;
  // Voice pills, white text on each. Adjusted for AA, 2026-10-09, by the
  // smallest HSL lightness step (0.005) that gives white text 4.5:1:
  // Soprano sampled #FF3988 (3.39:1) −0.155 → #E9005D (4.54:1);
  // Alto sampled #A570E4 (3.48:1) −0.065 → #9354DF (4.59:1);
  // Tenor sampled #49D149 (2.00:1) −0.22 → #228822 (4.55:1);
  // Bass sampled #4CA2E4 (2.76:1) −0.16 → #1D7AC1 (4.56:1).
  static const Color mixerSoprano = Color(0xFFE9005D);
  static const Color mixerAlto = Color(0xFF9354DF);
  static const Color mixerTenor = Color(0xFF228822);
  static const Color mixerBass = Color(0xFF1D7AC1);
  // Speaker icons. Sampled #272960 (= playbackNavy, 13.36:1).
  static const Color mixerSpeaker = playbackNavy;
  // Sliders (both sheets). Sampled: the part left of the thumb is white
  // with a #4F52A1 outline (6.88:1), the part right of it #272960
  // (= playbackNavy); the thumb is white with the same outline.
  static const Color sliderOutline = Color(0xFF4F52A1);
  static const Color sliderInactive = playbackNavy;
  // Mute pill, off: fill sampled #D7E4E9 (= playbackChipFill); text
  // sampled #7993A5 is 2.48:1 on it, so playbackChipText #506777 (4.56:1),
  // the same fix as the voice chips.
  static const Color mixerMuteFill = playbackChipFill;
  static const Color mixerMuteText = playbackChipText;
  // Adjusted for AA, 2026-10-09: Mute pill, on, sampled #FF395A (white text
  // 3.51:1); HSL lightness −0.145 gives #EE0028 (4.5:1).
  static const Color mixerMuteOn = Color(0xFFEE0028);
  // Speed sheet's metronome glyph. Sampled #1E9DCC (3.11:1; icon floor).
  static const Color speedMetronome = Color(0xFF1E9DCC);

  // Export Audio modal (PIYA-211), dropper-sampled from
  // references/PIYA211_ExportAudioModal_UI_1.png and _UI_2.png
  // (2026-10-17). Handle, title, voice pills, close X, checkboxes,
  // dividers and scrim sample to the Mixer's tokens above and reuse them;
  // the "All Voices" pill samples #272960 (= playbackNavy, white 13.36:1).
  static const Color exportAllVoicesPill = playbackNavy;
  // Adjusted for AA, 2026-10-17: "Download Audio" is a left-to-right
  // gradient sampled #39C2D6 → #1794CA, white text 2.13:1 → 3.43:1. The
  // label is drawn at 18 sp bold (large text, 3:1 floor, as
  // processingCancel), so only the left stop moves: HSL lightness −0.105
  // (smallest 0.005 step) → #25A2B4 (3.04:1). The right stop is kept.
  static const LinearGradient exportDownloadGradient = LinearGradient(
    colors: [Color(0xFF25A2B4), Color(0xFF1794CA)],
  );
  // Success dialog: title sampled #383838 (= sheetText) on white.
  // Adjusted for AA, 2026-10-17: the OK pill sampled #38A3D5
  // (= onboardingButtonBlue, white 2.85:1); at 18 sp bold, HSL lightness
  // −0.025 → #2D9ED3 (3.02:1).
  static const Color exportOkFill = Color(0xFF2D9ED3);

  // Settings (PIYA-212). No mockup exists, so every token here is derived,
  // not sampled: the screen reuses the Library header/nav and background,
  // and these only name the brand colours its groups are drawn with.
  // Derived (not sampled): group surfaces are plain white cards on
  // libraryBackground, as the Library's cards sit on it.
  static const Color settingsSurface = Colors.white;
  // Derived (not sampled): secondary text inside the white groups, the
  // Playback grey (#767676, 4.54:1 on white).
  static const Color settingsSubtle = playbackSubtle;
  // Derived (not sampled): group names sit on libraryBackground, where
  // #767676 is only 3.71:1, so they use the Library's card subtitle grey
  // (#575757, 5.90:1 on #E8E8E8) instead.
  static const Color settingsGroupLabel = libraryScoreSubtitle;
  // Derived (not sampled): row text, the sheets' #383838 (11.73:1).
  static const Color settingsText = sheetText;
  // Derived (not sampled): row dividers, the sheets' #E8E8E8.
  static const Color settingsDivider = sheetDivider;
  // Derived (not sampled): help "?" icon, the sheets' close-X grey
  // (#939393, 3.07:1, over the 3:1 icon floor).
  static const Color settingsHelpIcon = sheetClose;
  // Derived (not sampled): tempo stepper buttons, Playback navy with a
  // white glyph (13.36:1).
  static const Color settingsStepperFill = playbackNavy;
  // Derived (not sampled): "Log out" text. processingCancel #DF5757 is
  // only 3.72:1 on white, too low for 16 sp text, so it is darkened to
  // #D93636 (4.63:1) keeping the hue.
  static const Color settingsLogOut = Color(0xFFD93636);

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
