import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

/// Shared Login/Sign-Up layout from the PIYA-202 reference: a brand-gradient
/// hero headline above a white, top-rounded sheet holding the form.
///
/// The whole page is one scroll view filled to viewport height, so on short
/// screens or with the keyboard up the form scrolls instead of throwing a
/// RenderFlex overflow (the failure PIYA-201's VoiceSelectionStep hit).
class AuthScaffold extends StatelessWidget {
  const AuthScaffold({
    super.key,
    required this.headline,
    required this.accentHeadline,
    required this.title,
    required this.switchPrompt,
    required this.children,
  });

  /// First headline line, in white.
  final String headline;

  /// Second headline line, in the lighter accent tint (the reference's
  /// two-tone heading).
  final String accentHeadline;

  /// Sheet title, e.g. "Log In".
  final String title;

  /// "Don't have an account? Sign Up"-style link under the title.
  final Widget switchPrompt;

  final List<Widget> children;

  static const double _sheetRadius = 32;
  static const double _horizontalPadding = 24;
  static const double _sheetTopPadding = 32;
  static const double _sheetBottomPadding = 24;
  static const double _titleToPromptGap = 4;
  static const double _promptToFormGap = 24;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final bottomInset = MediaQuery.paddingOf(context).bottom;

    return Scaffold(
      backgroundColor: Colors.white,
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: AppTheme.authHeaderGradient),
        child: CustomScrollView(
          slivers: [
            SliverFillRemaining(
              hasScrollBody: false,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SafeArea(
                    bottom: false,
                    child: _AuthHeader(
                      headline: headline,
                      accentHeadline: accentHeadline,
                    ),
                  ),
                  Expanded(
                    child: DecoratedBox(
                      decoration: const BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.vertical(
                          top: Radius.circular(_sheetRadius),
                        ),
                      ),
                      child: Padding(
                        padding: EdgeInsets.fromLTRB(
                          _horizontalPadding,
                          _sheetTopPadding,
                          _horizontalPadding,
                          _sheetBottomPadding + bottomInset,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Text(
                              title,
                              textAlign: TextAlign.center,
                              style: textTheme.headlineMedium?.copyWith(
                                fontWeight: FontWeight.w700,
                                color: AppTheme.onboardingHeadingDark,
                              ),
                            ),
                            const SizedBox(height: _titleToPromptGap),
                            switchPrompt,
                            const SizedBox(height: _promptToFormGap),
                            ...children,
                          ],
                        ),
                      ),
                    ),
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

class _AuthHeader extends StatelessWidget {
  const _AuthHeader({required this.headline, required this.accentHeadline});

  final String headline;
  final String accentHeadline;

  static const EdgeInsets _padding = EdgeInsets.fromLTRB(24, 32, 24, 40);
  static const double _decorationSize = 140;
  // Purely decorative stand-in for the reference's gear illustration — kept
  // faint so it never competes with the headline for contrast.
  static const double _decorationAlpha = 0.14;

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).textTheme.headlineMedium?.copyWith(
          fontWeight: FontWeight.w700,
          height: 1.25,
          color: Colors.white,
        );

    return Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned(
          right: -16,
          bottom: -8,
          child: ExcludeSemantics(
            child: Icon(
              Icons.music_note_rounded,
              size: _decorationSize,
              color: Colors.white.withValues(alpha: _decorationAlpha),
            ),
          ),
        ),
        Padding(
          padding: _padding,
          child: Text.rich(
            TextSpan(
              children: [
                TextSpan(text: '$headline\n'),
                TextSpan(
                  text: accentHeadline,
                  style: TextStyle(color: AppTheme.authHeadlineAccent),
                ),
              ],
            ),
            style: style,
          ),
        ),
      ],
    );
  }
}
