import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

/// How long one splash play lasts. Same as the onboarding intro it was
/// taken from (PIYA-201-V2.2 AC4: no longer than that intro).
const splashIntroDuration = Duration(milliseconds: 4600);

// Intro sequence (icon fade-in -> joins wordmark -> whole splash fades to
// reveal the screen beneath) timing, phased as fractions of the
// controller's 0.0-1.0 range. Eyeballed — no Figma frame exists for this
// sequence, so these are tunable, not pinned.
const _iconFadeInterval = Interval(0.1, 0.2, curve: Curves.easeIn);
const _joinInterval = Interval(0.4, 0.8, curve: Curves.easeOut);
const _handoffInterval = Interval(0.8, 1.0, curve: Curves.easeInOut);

// Lockup geometry. The icon fades in at a larger "solo" size, then shrinks
// down to the lockup size as it slides in next to the text. The icon
// asset's canvas is square, so width == height at any scale. The text
// asset's canvas is 2000x596, so its width is derived from height via that
// aspect ratio.
const _soloIconSize = 120.0;
const _splashIconSize = 88.0;
const _splashTextHeight = 50.0;
const _splashTextAspect = 2000 / 596;
const _lockupGap = -20.0;
const _textSlideInOffset = 20.0;
const _iconEntranceStartScale = 0.85;
const _statusBarClearance = 8.0;

// Vertical anchor for the lockup: "near the top, not dead-center" per the
// reference request, expressed as a fraction of screen height so it scales
// across device sizes; clamped so it never crowds the status bar.
const _logoAnchorFraction = 0.30;

/// The PiyaNota logo intro (PIYA-201): icon fade-in -> joins wordmark ->
/// the whole layer fades away to reveal whatever is beneath it.
///
/// It used to live inside the onboarding flow; it now stands alone so
/// `SplashGate` can play it over any screen on cold start and resume.
/// Plays once from mount, then calls [onFinished].
class SplashOverlay extends StatefulWidget {
  const SplashOverlay({super.key, required this.onFinished});

  final VoidCallback onFinished;

  @override
  State<SplashOverlay> createState() => _SplashOverlayState();
}

class _SplashOverlayState extends State<SplashOverlay>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  bool _finished = false;

  @override
  void initState() {
    super.initState();
    _controller =
        AnimationController(vsync: this, duration: splashIntroDuration)
          ..addListener(_finishAtEnd)
          ..forward();
  }

  /// Finishes on the frame the value reaches 1.0, not on `completed`, which
  /// fires one frame later: the splash then ends at exactly
  /// [splashIntroDuration], like the old intro unblocked onboarding (AC4).
  void _finishAtEnd() {
    if (_finished || _controller.value < 1.0) return;
    _finished = true;
    widget.onFinished();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    final topInset = MediaQuery.of(context).padding.top;
    final logoAnchorY = (size.height * _logoAnchorFraction).clamp(
      topInset + _soloIconSize / 2 + _statusBarClearance,
      size.height,
    );
    final groupCenter = Offset(size.width / 2, logoAnchorY);

    return Semantics(
      label: 'PiyaNota',
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          final t = _controller.value;
          final iconFadeT = _iconFadeInterval.transform(t);
          final joinT = _joinInterval.transform(t);
          final splashOpacity = 1 - _handoffInterval.transform(t);

          final textWidth = _splashTextHeight * _splashTextAspect;
          final lockupWidth = _splashIconSize + _lockupGap + textWidth;
          final iconLocalX = -(lockupWidth / 2 - _splashIconSize / 2);
          final textLocalX = lockupWidth / 2 - textWidth / 2;

          final iconSize = lerpDouble(_soloIconSize, _splashIconSize, joinT)!;
          final iconEntranceScale = lerpDouble(
            _iconEntranceStartScale,
            1.0,
            iconFadeT,
          )!;
          final iconX = lerpDouble(0, iconLocalX, joinT)!;
          final textX = lerpDouble(
            textLocalX + _textSlideInOffset,
            textLocalX,
            joinT,
          )!;

          return Opacity(
            opacity: splashOpacity,
            child: Container(
              decoration: const BoxDecoration(
                gradient: AppTheme.primaryGradient,
              ),
              width: double.infinity,
              height: double.infinity,
              child: Stack(
                children: [
                  _LogoPiece(
                    asset: 'assets/branding/Piyanota_App_Logo.png',
                    center: groupCenter + Offset(iconX, 0),
                    width: iconSize * iconEntranceScale,
                    height: iconSize * iconEntranceScale,
                    opacity: iconFadeT,
                  ),
                  _LogoPiece(
                    asset: 'assets/branding/Piyanota_iyanota-text_logo.png',
                    center: groupCenter + Offset(textX, 0),
                    width: textWidth,
                    height: _splashTextHeight,
                    opacity: joinT,
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _LogoPiece extends StatelessWidget {
  const _LogoPiece({
    required this.asset,
    required this.center,
    required this.width,
    required this.height,
    required this.opacity,
  });

  final String asset;
  final Offset center;
  final double width;
  final double height;
  final double opacity;

  @override
  Widget build(BuildContext context) {
    if (opacity <= 0) return const SizedBox.shrink();
    return Positioned(
      left: center.dx - width / 2,
      top: center.dy - height / 2,
      width: width,
      height: height,
      child: Opacity(
        opacity: opacity,
        child: Image.asset(asset, fit: BoxFit.contain),
      ),
    );
  }
}
