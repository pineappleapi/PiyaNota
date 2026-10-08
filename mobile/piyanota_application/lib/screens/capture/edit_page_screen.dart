import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/page_edit.dart';
import '../../state/capture_providers.dart';
import '../../theme/app_theme.dart';
import 'capture_messages.dart';

/// Edit Page (PIYA-206 ✎): crop with four corner handles, rotate 90°, and
/// straighten up to ±45°. The preview uses the same [PageEdit] maths as the
/// isolate that writes the file, so the saved page matches what was shown.
/// Pops with the new file's path, or null when nothing changed.
class EditPageScreen extends ConsumerStatefulWidget {
  const EditPageScreen({super.key, required this.path});

  final String path;

  @override
  ConsumerState<EditPageScreen> createState() => _EditPageScreenState();
}

class _EditPageScreenState extends ConsumerState<EditPageScreen> {
  Size? _source;
  bool _loadFailed = false;
  PageEdit _edit = const PageEdit();
  bool _straightening = false;
  bool _saving = false;

  /// Corner currently being dragged.
  Alignment? _activeCorner;

  /// How close (logical px) a touch must start to a corner to grab it.
  static const double _grabRadius = 36;
  static const double _framePadding = 24;

  @override
  void initState() {
    super.initState();
    _loadSize();
  }

  Future<void> _loadSize() async {
    try {
      final size = await ref.read(pageImageSourceProvider).sizeOf(widget.path);
      if (mounted) setState(() => _source = size);
    } catch (e) {
      debugPrint('Edit Page could not read the image size: $e');
      if (mounted) setState(() => _loadFailed = true);
    }
  }

  Future<void> _done() async {
    if (_saving) return;
    if (_edit.isIdentity) {
      Navigator.of(context).pop();
      return;
    }
    setState(() => _saving = true);
    try {
      final path = await ref
          .read(pageImageProcessorProvider)
          .applyEdit(widget.path, _edit);
      if (mounted) Navigator.of(context).pop(path);
    } catch (e) {
      debugPrint('Edit Page could not save: $e');
      if (!mounted) return;
      setState(() => _saving = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text(CaptureMessages.editFailed)));
    }
  }

  void _panStart(Offset local, Size frame) {
    final crop = _edit.crop;
    Alignment? best;
    var bestDistance = _grabRadius;
    for (final corner in const [
      Alignment.topLeft,
      Alignment.topRight,
      Alignment.bottomLeft,
      Alignment.bottomRight,
    ]) {
      final point = Offset(
        (corner.x < 0 ? crop.left : crop.right) * frame.width,
        (corner.y < 0 ? crop.top : crop.bottom) * frame.height,
      );
      final distance = (point - local).distance;
      if (distance <= bestDistance) {
        best = corner;
        bestDistance = distance;
      }
    }
    setState(() => _activeCorner = best);
  }

  void _panUpdate(Offset local, Size frame) {
    final corner = _activeCorner;
    if (corner == null) return;
    setState(() {
      _edit = _edit.copyWith(
        crop: dragCropCorner(
          _edit.crop,
          corner,
          Offset(local.dx / frame.width, local.dy / frame.height),
        ),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final source = _source;
    final textTheme = Theme.of(context).textTheme;
    return PopScope(
      canPop: !_saving,
      child: Scaffold(
        backgroundColor: AppTheme.captureInk,
        appBar: AppBar(
          backgroundColor: AppTheme.captureInk,
          foregroundColor: Colors.white,
          title: const Text(CaptureMessages.editTitle),
          leading: IconButton(
            tooltip: CaptureMessages.cancel,
            icon: const Icon(Icons.close_rounded),
            onPressed: _saving ? null : () => Navigator.of(context).pop(),
          ),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: FilledButton(
                onPressed: source == null || _saving ? null : _done,
                style: FilledButton.styleFrom(
                  backgroundColor: AppTheme.captureAccent,
                  foregroundColor: AppTheme.captureInk,
                  minimumSize: const Size(64, 48),
                ),
                child: _saving
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          color: AppTheme.captureInk,
                          semanticsLabel: CaptureMessages.applyingEdit,
                        ),
                      )
                    : const Text(CaptureMessages.done),
              ),
            ),
          ],
        ),
        body: SafeArea(
          child: Column(
            children: [
              Expanded(
                child: source == null
                    ? Center(
                        child: _loadFailed
                            ? Text(
                                CaptureMessages.editFailed,
                                textAlign: TextAlign.center,
                                style: textTheme.bodyMedium?.copyWith(
                                  color: Colors.white,
                                ),
                              )
                            : const CircularProgressIndicator(
                                color: AppTheme.captureAccent,
                              ),
                      )
                    : Padding(
                        padding: const EdgeInsets.all(_framePadding),
                        child: _buildCanvas(source),
                      ),
              ),
              _Controls(
                edit: _edit,
                enabled: source != null && !_saving,
                onRotate: () =>
                    setState(() => _edit = _edit.rotatedClockwise()),
                onReset: () => setState(() => _edit = const PageEdit()),
                onStraighten: (value) => setState(
                  () => _edit = _edit.copyWith(straightenDegrees: value),
                ),
                onStraightenStart: () => setState(() => _straightening = true),
                onStraightenEnd: () => setState(() => _straightening = false),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCanvas(Size source) {
    final turned = rotatedSize(source, _edit.quarterTurns);
    final theta = _edit.straightenDegrees * math.pi / 180;
    final scale = coverScale(turned, theta);
    return LayoutBuilder(
      builder: (context, constraints) {
        final fit = math.min(
          constraints.maxWidth / turned.width,
          constraints.maxHeight / turned.height,
        );
        final frame = Size(turned.width * fit, turned.height * fit);
        return Center(
          child: SizedBox.fromSize(
            size: frame,
            child: GestureDetector(
              onPanStart: _saving
                  ? null
                  : (d) => _panStart(d.localPosition, frame),
              onPanUpdate: _saving
                  ? null
                  : (d) => _panUpdate(d.localPosition, frame),
              onPanEnd: (_) => setState(() => _activeCorner = null),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  ClipRect(
                    // Same mapping as frameToSource, inverted: the turned
                    // page is rotated by θ and zoomed by coverScale about
                    // the frame centre.
                    child: Transform(
                      alignment: Alignment.center,
                      transform: Matrix4.identity()
                        ..rotateZ(theta)
                        ..scaleByDouble(scale, scale, 1, 1),
                      child: RotatedBox(
                        quarterTurns: _edit.quarterTurns,
                        child: Image(
                          image: ref
                              .read(pageImageSourceProvider)
                              .imageFor(widget.path),
                          fit: BoxFit.fill,
                          gaplessPlayback: true,
                        ),
                      ),
                    ),
                  ),
                  IgnorePointer(
                    child: CustomPaint(
                      painter: CropOverlayPainter(
                        crop: _edit.crop,
                        showGrid: _straightening,
                        activeCorner: _activeCorner,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _Controls extends StatelessWidget {
  const _Controls({
    required this.edit,
    required this.enabled,
    required this.onRotate,
    required this.onReset,
    required this.onStraighten,
    required this.onStraightenStart,
    required this.onStraightenEnd,
  });

  final PageEdit edit;
  final bool enabled;
  final VoidCallback onRotate;
  final VoidCallback onReset;
  final ValueChanged<double> onStraighten;
  final VoidCallback onStraightenStart;
  final VoidCallback onStraightenEnd;

  @override
  Widget build(BuildContext context) {
    const white = TextStyle(color: Colors.white);
    final buttonStyle = TextButton.styleFrom(
      foregroundColor: AppTheme.captureAccent,
      minimumSize: const Size(48, 48),
    );
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Label and value above a full-width slider, so 2x text on a
          // 320 dp phone can't squeeze the slider out of its row (NFR-10).
          Row(
            children: [
              Expanded(child: Text(CaptureMessages.straighten, style: white)),
              ExcludeSemantics(
                child: Text(
                  CaptureMessages.straightenValue(edit.straightenDegrees),
                  style: white,
                ),
              ),
            ],
          ),
          Slider(
            value: edit.straightenDegrees,
            min: -PageEdit.maxStraighten,
            max: PageEdit.maxStraighten,
            divisions: (PageEdit.maxStraighten * 4).round(),
            activeColor: AppTheme.captureAccent,
            label: CaptureMessages.straightenValue(edit.straightenDegrees),
            semanticFormatterCallback: CaptureMessages.straightenValue,
            onChangeStart: enabled ? (_) => onStraightenStart() : null,
            onChangeEnd: enabled ? (_) => onStraightenEnd() : null,
            onChanged: enabled ? onStraighten : null,
          ),
          Wrap(
            alignment: WrapAlignment.spaceEvenly,
            spacing: 16,
            children: [
              TextButton.icon(
                style: buttonStyle,
                onPressed: enabled ? onRotate : null,
                icon: const Icon(Icons.rotate_90_degrees_cw_outlined),
                label: const Text(CaptureMessages.rotate),
              ),
              TextButton.icon(
                style: buttonStyle,
                onPressed: enabled && !edit.isIdentity ? onReset : null,
                icon: const Icon(Icons.restart_alt_rounded),
                label: const Text(CaptureMessages.reset),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Dims everything outside the crop, outlines it, draws the four corner
/// handles, and a grid while straightening so lines can be matched to it.
class CropOverlayPainter extends CustomPainter {
  const CropOverlayPainter({
    required this.crop,
    required this.showGrid,
    this.activeCorner,
  });

  final Rect crop;
  final bool showGrid;
  final Alignment? activeCorner;

  static const int _gridLines = 6;
  static const double _handleArm = 22;

  @override
  void paint(Canvas canvas, Size size) {
    final whole = Offset.zero & size;
    final rect = Rect.fromLTRB(
      crop.left * size.width,
      crop.top * size.height,
      crop.right * size.width,
      crop.bottom * size.height,
    );
    canvas.drawPath(
      Path()
        ..fillType = PathFillType.evenOdd
        ..addRect(whole)
        ..addRect(rect),
      Paint()..color = Colors.black.withValues(alpha: 0.6),
    );
    if (showGrid) {
      final grid = Paint()
        ..color = Colors.white.withValues(alpha: 0.5)
        ..strokeWidth = 1;
      for (var i = 1; i < _gridLines; i++) {
        final x = size.width * i / _gridLines;
        final y = size.height * i / _gridLines;
        canvas
          ..drawLine(Offset(x, 0), Offset(x, size.height), grid)
          ..drawLine(Offset(0, y), Offset(size.width, y), grid);
      }
    }
    canvas.drawRect(
      rect,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5,
    );
    for (final corner in const [
      Alignment.topLeft,
      Alignment.topRight,
      Alignment.bottomLeft,
      Alignment.bottomRight,
    ]) {
      final p = Offset(
        corner.x < 0 ? rect.left : rect.right,
        corner.y < 0 ? rect.top : rect.bottom,
      );
      final handle = Paint()
        ..color = corner == activeCorner ? Colors.white : AppTheme.captureAccent
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 4;
      final dx = corner.x < 0 ? 1.0 : -1.0;
      final dy = corner.y < 0 ? 1.0 : -1.0;
      canvas.drawPath(
        Path()
          ..moveTo(p.dx + dx * _handleArm, p.dy)
          ..lineTo(p.dx, p.dy)
          ..lineTo(p.dx, p.dy + dy * _handleArm),
        handle,
      );
    }
  }

  @override
  bool shouldRepaint(CropOverlayPainter oldDelegate) =>
      oldDelegate.crop != crop ||
      oldDelegate.showGrid != showGrid ||
      oldDelegate.activeCorner != activeCorner;
}
