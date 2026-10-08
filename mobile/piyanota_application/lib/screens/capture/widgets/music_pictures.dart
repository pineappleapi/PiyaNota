import 'package:flutter/material.dart';

import '../../../models/score_details.dart';
import '../../../theme/app_theme.dart';

/// Staff positions of each accidental in a key signature, in half staff
/// spaces down from the top line (treble F5 = 0). Standard engraving
/// order: sharps F C G D A E B, flats B E A D G C F.
const List<int> sharpPositions = [0, 3, -1, 2, 5, 1, 4];
const List<int> flatPositions = [4, 1, 5, 2, 6, 3, 7];

/// Positions for [key]'s accidentals, in the order they are written.
List<int> keySignaturePositions(KeySignature key) =>
    (key.isFlat ? flatPositions : sharpPositions).take(key.count).toList();

/// A short treble staff with [keySignature]'s sharps or flats, as a singer
/// sees them at the start of each line. Null draws the bare staff. Drawn
/// with paths, not font glyphs, because ♯/♭ coverage varies by device font.
class KeySignatureStaff extends StatelessWidget {
  const KeySignatureStaff({
    super.key,
    required this.keySignature,
    this.color = AppTheme.captureInk,
    this.height = 44,
  });

  final KeySignature? keySignature;
  final Color color;
  final double height;

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: CustomPaint(
        size: Size(height * 2.2, height),
        painter: KeySignaturePainter(keySignature: keySignature, color: color),
      ),
    );
  }
}

class KeySignaturePainter extends CustomPainter {
  KeySignaturePainter({required this.keySignature, required this.color});

  final KeySignature? keySignature;
  final Color color;

  /// The staff spans 4 spaces; leave room for the G5 sharp above it and
  /// the F4 flat's stem below it.
  static const double _spacesTall = 7;
  static const double _staffTopInSpaces = 1.5;
  static const double _lineWidthInSpaces = 0.1;
  static const double _accidentalStepInSpaces = 1.1;
  static const double _leftPadInSpaces = 0.8;

  @override
  void paint(Canvas canvas, Size size) {
    final space = size.height / _spacesTall;
    final top = space * _staffTopInSpaces;
    final line = Paint()
      ..color = color.withValues(alpha: 0.55)
      ..strokeWidth = space * _lineWidthInSpaces;
    for (var i = 0; i < 5; i++) {
      final y = top + i * space;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), line);
    }
    final key = keySignature;
    if (key == null || key.count == 0) return;
    final ink = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.butt;
    final positions = keySignaturePositions(key);
    for (var i = 0; i < positions.length; i++) {
      final centre = Offset(
        space * (_leftPadInSpaces + 0.5 + i * _accidentalStepInSpaces),
        top + positions[i] * space / 2,
      );
      if (key.isFlat) {
        _flat(canvas, centre, space, ink);
      } else {
        _sharp(canvas, centre, space, ink);
      }
    }
  }

  void _sharp(Canvas canvas, Offset c, double space, Paint ink) {
    final stem = ink..strokeWidth = space * 0.12;
    final dx = space * 0.22;
    canvas
      ..drawLine(
        c + Offset(-dx, -space * 1.2),
        c + Offset(-dx, space * 1.35),
        stem,
      )
      ..drawLine(
        c + Offset(dx, -space * 1.35),
        c + Offset(dx, space * 1.2),
        stem,
      );
    final bar = Paint()
      ..color = color
      ..strokeWidth = space * 0.3;
    final w = space * 0.5;
    for (final y in [-space * 0.4, space * 0.4]) {
      canvas.drawLine(
        c + Offset(-w, y + space * 0.15),
        c + Offset(w, y - space * 0.15),
        bar,
      );
    }
  }

  void _flat(Canvas canvas, Offset c, double space, Paint ink) {
    final stemX = c.dx - space * 0.3;
    canvas.drawLine(
      Offset(stemX, c.dy - space * 1.9),
      Offset(stemX, c.dy + space * 0.5),
      ink..strokeWidth = space * 0.12,
    );
    final bowl = Path()
      ..moveTo(stemX, c.dy + space * 0.5)
      ..cubicTo(
        c.dx + space * 0.7,
        c.dy - space * 0.05,
        c.dx + space * 0.35,
        c.dy - space * 0.75,
        stemX,
        c.dy - space * 0.15,
      );
    canvas.drawPath(bowl, ink..strokeWidth = space * 0.2);
  }

  @override
  bool shouldRepaint(KeySignaturePainter oldDelegate) =>
      oldDelegate.keySignature != keySignature || oldDelegate.color != color;
}

/// A time signature as printed: two numbers stacked. "Other" and "Not sure"
/// show a question mark.
class StackedTimeSignature extends StatelessWidget {
  const StackedTimeSignature({
    super.key,
    required this.timeSignature,
    this.fontSize = 22,
    this.color = AppTheme.captureInk,
  });

  final TimeSignature? timeSignature;
  final double fontSize;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(
      fontSize: fontSize,
      height: 1,
      fontWeight: FontWeight.w800,
      color: color,
    );
    final beats = timeSignature?.beats;
    final unit = timeSignature?.unit;
    return ExcludeSemantics(
      child: beats == null || unit == null
          ? Text('?', style: style.copyWith(fontSize: fontSize * 1.6))
          : Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(beats, style: style),
                Text(unit, style: style),
              ],
            ),
    );
  }
}
