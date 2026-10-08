import 'package:flutter/material.dart';

import '../../../services/capture/capture_camera.dart';
import '../../../theme/app_theme.dart';
import '../capture_messages.dart';

/// What the camera frame is showing.
enum CameraStatus {
  starting,
  ready,

  /// Permission denied this time; asking again can still show the dialog.
  denied,

  /// Permission blocked ("don't ask again"); only Settings can fix it.
  blocked,
  unavailable,
}

/// The dark rounded frame from the mockup: live preview (or a status
/// message) under cyan corner brackets, with tap-to-focus.
class CameraFrame extends StatefulWidget {
  const CameraFrame({
    super.key,
    required this.status,
    required this.camera,
    required this.onAllowCamera,
    required this.onOpenSettings,
    this.overlay,
  });

  final CameraStatus status;
  final CaptureCamera? camera;
  final VoidCallback onAllowCamera;
  final VoidCallback onOpenSettings;

  /// Shown on top, e.g. "Preparing page".
  final Widget? overlay;

  @override
  State<CameraFrame> createState() => _CameraFrameState();
}

class _CameraFrameState extends State<CameraFrame> {
  Offset? _focusMark;
  int _focusGeneration = 0;

  static const double _radius = 20;
  static const double _focusRingSize = 56;
  static const Duration _focusMarkDuration = Duration(milliseconds: 900);

  Future<void> _focus(Offset local, Size frame) async {
    final camera = widget.camera;
    if (camera == null || widget.status != CameraStatus.ready) return;
    final generation = ++_focusGeneration;
    setState(() => _focusMark = local);
    await camera.focusAt(
      previewPointFor(local, frame, camera.previewAspectRatio),
    );
    await Future<void>.delayed(_focusMarkDuration);
    if (mounted && generation == _focusGeneration) {
      setState(() => _focusMark = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final camera = widget.camera;
    final live = widget.status == CameraStatus.ready && camera != null;
    return ClipRRect(
      borderRadius: BorderRadius.circular(_radius),
      child: ColoredBox(
        color: AppTheme.captureInk,
        child: LayoutBuilder(
          builder: (context, constraints) {
            final size = constraints.biggest;
            // A screen-reader double tap can't aim, so it focuses the
            // centre, where the page usually is.
            return Semantics(
              label: live ? CaptureMessages.cameraPreview : null,
              onTap: live ? () => _focus(size.center(Offset.zero), size) : null,
              child: GestureDetector(
                excludeFromSemantics: true,
                onTapUp: live ? (d) => _focus(d.localPosition, size) : null,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    if (live)
                      FittedBox(
                        fit: BoxFit.cover,
                        clipBehavior: Clip.hardEdge,
                        child: SizedBox(
                          width: 1000,
                          height: 1000 / camera.previewAspectRatio,
                          child: camera.buildPreview(),
                        ),
                      )
                    else
                      _StatusMessage(
                        status: widget.status,
                        onAllowCamera: widget.onAllowCamera,
                        onOpenSettings: widget.onOpenSettings,
                      ),
                    const IgnorePointer(
                      child: CustomPaint(painter: CornerBracketsPainter()),
                    ),
                    if (_focusMark case final mark?)
                      Positioned(
                        left: mark.dx - _focusRingSize / 2,
                        top: mark.dy - _focusRingSize / 2,
                        child: IgnorePointer(
                          child: Container(
                            width: _focusRingSize,
                            height: _focusRingSize,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              border: Border.all(
                                color: AppTheme.captureAccent,
                                width: 2,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ?widget.overlay,
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

/// Maps a tap in a [frame]-sized box to the 0–1 point in a preview of
/// [aspectRatio] (width / height) scaled to cover the box, as the camera
/// plugin's focus point expects.
Offset previewPointFor(Offset tap, Size frame, double aspectRatio) {
  final scale = frame.width / aspectRatio > frame.height
      ? frame.width / aspectRatio
      : frame.height;
  final shown = Size(aspectRatio * scale, scale);
  final offset = Offset(
    (frame.width - shown.width) / 2,
    (frame.height - shown.height) / 2,
  );
  final p = tap - offset;
  return Offset(
    (p.dx / shown.width).clamp(0.0, 1.0),
    (p.dy / shown.height).clamp(0.0, 1.0),
  );
}

class _StatusMessage extends StatelessWidget {
  const _StatusMessage({
    required this.status,
    required this.onAllowCamera,
    required this.onOpenSettings,
  });

  final CameraStatus status;
  final VoidCallback onAllowCamera;
  final VoidCallback onOpenSettings;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    const white = Colors.white;
    final List<Widget> content = switch (status) {
      CameraStatus.starting || CameraStatus.ready => [
        const SizedBox.square(
          dimension: 28,
          child: CircularProgressIndicator(
            color: AppTheme.captureAccent,
            strokeWidth: 3,
          ),
        ),
        const SizedBox(height: 12),
        Text(
          CaptureMessages.cameraStarting,
          style: textTheme.bodyMedium?.copyWith(color: white),
        ),
      ],
      CameraStatus.denied || CameraStatus.blocked => [
        const Icon(
          Icons.no_photography_outlined,
          size: 40,
          color: AppTheme.captureAccent,
        ),
        const SizedBox(height: 8),
        Text(
          CaptureMessages.cameraNeededTitle,
          textAlign: TextAlign.center,
          style: textTheme.titleMedium?.copyWith(
            color: white,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          CaptureMessages.cameraNeededBody,
          textAlign: TextAlign.center,
          style: textTheme.bodyMedium?.copyWith(color: white),
        ),
        const SizedBox(height: 12),
        Wrap(
          alignment: WrapAlignment.center,
          spacing: 8,
          runSpacing: 8,
          children: [
            if (status == CameraStatus.denied)
              OutlinedButton(
                onPressed: onAllowCamera,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppTheme.captureAccent,
                  side: const BorderSide(color: AppTheme.captureAccent),
                  minimumSize: const Size(48, 48),
                ),
                child: const Text(CaptureMessages.allowCamera),
              ),
            FilledButton(
              onPressed: onOpenSettings,
              style: FilledButton.styleFrom(
                backgroundColor: AppTheme.captureAccent,
                foregroundColor: AppTheme.captureInk,
                minimumSize: const Size(48, 48),
              ),
              child: const Text(CaptureMessages.openSettings),
            ),
          ],
        ),
      ],
      CameraStatus.unavailable => [
        const Icon(
          Icons.no_photography_outlined,
          size: 40,
          color: AppTheme.captureAccent,
        ),
        const SizedBox(height: 8),
        Text(
          CaptureMessages.noCamera,
          textAlign: TextAlign.center,
          style: textTheme.bodyMedium?.copyWith(color: white),
        ),
      ],
    };
    return Stack(
      fit: StackFit.expand,
      children: [
        const ExcludeSemantics(
          child: Center(
            child: Icon(
              Icons.queue_music_rounded,
              size: 160,
              color: AppTheme.capturePlaceholderGlyph,
            ),
          ),
        ),
        Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: Semantics(
              liveRegion: true,
              child: Column(mainAxisSize: MainAxisSize.min, children: content),
            ),
          ),
        ),
      ],
    );
  }
}

/// The mockup's four cyan corner brackets.
class CornerBracketsPainter extends CustomPainter {
  const CornerBracketsPainter();

  static const double _inset = 14;
  static const double _arm = 30;
  static const double _radius = 12;
  static const double _stroke = 3.5;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppTheme.captureAccent
      ..style = PaintingStyle.stroke
      ..strokeWidth = _stroke
      ..strokeCap = StrokeCap.round;
    const i = _inset;
    final r = size.width - _inset;
    final b = size.height - _inset;
    // Each bracket: arm along the edge, rounded corner, arm down the side.
    void bracket(Offset corner, double dx, double dy) {
      final path = Path()
        ..moveTo(corner.dx + dx * _arm, corner.dy)
        ..lineTo(corner.dx + dx * _radius, corner.dy)
        ..quadraticBezierTo(
          corner.dx,
          corner.dy,
          corner.dx,
          corner.dy + dy * _radius,
        )
        ..lineTo(corner.dx, corner.dy + dy * _arm);
      canvas.drawPath(path, paint);
    }

    bracket(const Offset(i, i), 1, 1);
    bracket(Offset(r, i), -1, 1);
    bracket(Offset(i, b), 1, -1);
    bracket(Offset(r, b), -1, -1);
  }

  @override
  bool shouldRepaint(CornerBracketsPainter oldDelegate) => false;
}
