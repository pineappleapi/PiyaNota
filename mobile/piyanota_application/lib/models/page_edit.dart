import 'dart:math' as math;
import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';

/// One Edit Page result (PIYA-206 ✎): quarter turns, then a straighten
/// angle, then a crop. The maths is shared by the editor preview and the
/// isolate that writes the new file, so what the user saw is what uploads.
///
/// Coordinates: the "frame" is the page after [quarterTurns] (size
/// [rotatedSize]). Straightening turns the picture inside that frame about
/// its centre by [straightenDegrees] (positive = clockwise on screen) and
/// zooms it by [coverScale] so no empty corners show. [crop] is a rectangle
/// in the frame, normalised to 0–1 on each axis.
@immutable
class PageEdit {
  const PageEdit({
    this.quarterTurns = 0,
    this.straightenDegrees = 0,
    this.crop = fullCrop,
  });

  static const Rect fullCrop = Rect.fromLTWH(0, 0, 1, 1);
  static const double maxStraighten = 45;

  /// Smallest crop side, as a share of the frame, so a handle can't collapse
  /// the page to nothing.
  static const double minCropFraction = 0.1;

  /// Clockwise, 0–3.
  final int quarterTurns;
  final double straightenDegrees;
  final Rect crop;

  bool get isIdentity =>
      quarterTurns % 4 == 0 && straightenDegrees == 0 && crop == fullCrop;

  PageEdit copyWith({
    int? quarterTurns,
    double? straightenDegrees,
    Rect? crop,
  }) => PageEdit(
    quarterTurns: (quarterTurns ?? this.quarterTurns) % 4,
    straightenDegrees: straightenDegrees ?? this.straightenDegrees,
    crop: crop ?? this.crop,
  );

  /// Turning the page swaps the frame's sides, so an old crop no longer
  /// means anything: it resets, as most photo editors do.
  PageEdit rotatedClockwise() =>
      PageEdit(quarterTurns: (quarterTurns + 1) % 4, crop: fullCrop);

  @override
  bool operator ==(Object other) =>
      other is PageEdit &&
      other.quarterTurns == quarterTurns &&
      other.straightenDegrees == straightenDegrees &&
      other.crop == crop;

  @override
  int get hashCode => Object.hash(quarterTurns, straightenDegrees, crop);
}

/// Size of a [source]-sized image after [quarterTurns] clockwise turns.
Size rotatedSize(Size source, int quarterTurns) =>
    quarterTurns.isOdd ? Size(source.height, source.width) : source;

/// Smallest zoom at which a picture turned by [radians] still fills a
/// [frame]-sized window: the window, turned back, must fit inside the
/// zoomed picture on both axes.
double coverScale(Size frame, double radians) {
  final c = math.cos(radians).abs();
  final s = math.sin(radians).abs();
  return math.max(
    c + (frame.height / frame.width) * s,
    c + (frame.width / frame.height) * s,
  );
}

/// Maps a point in the frame (in frame pixels) back to the original,
/// unrotated image's pixel coordinates.
Offset frameToSource(Offset framePoint, Size source, PageEdit edit) {
  final k = edit.quarterTurns % 4;
  final frame = rotatedSize(source, k);
  final theta = edit.straightenDegrees * math.pi / 180;
  final scale = coverScale(frame, theta);
  final centre = frame.center(Offset.zero);
  final d = framePoint - centre;
  // R(-θ) in y-down coordinates undoes the on-screen clockwise turn.
  final cosT = math.cos(theta);
  final sinT = math.sin(theta);
  final q =
      centre +
      Offset(d.dx * cosT + d.dy * sinT, -d.dx * sinT + d.dy * cosT) / scale;
  return quarterTurnToSource(q, source, k);
}

/// Undoes [quarterTurns] clockwise turns: a point in the turned image back
/// to the original. Continuous form of the `image` package's `copyRotate`
/// 90° step, `dst(x, y) = src(y, H - 1 - x)`.
Offset quarterTurnToSource(Offset turned, Size source, int quarterTurns) {
  final w = source.width;
  final h = source.height;
  switch (quarterTurns % 4) {
    case 1:
      return Offset(turned.dy, h - turned.dx);
    case 2:
      return Offset(w - turned.dx, h - turned.dy);
    case 3:
      return Offset(w - turned.dy, turned.dx);
    default:
      return turned;
  }
}

/// Pixel size of the edited output. One output pixel steps [coverScale]
/// frame pixels, i.e. one source pixel, so straightening never upsamples.
Size editedOutputSize(Size source, PageEdit edit) {
  final frame = rotatedSize(source, edit.quarterTurns);
  final scale = coverScale(frame, edit.straightenDegrees * math.pi / 180);
  return Size(
    math.max(1, (edit.crop.width * frame.width / scale).roundToDouble()),
    math.max(1, (edit.crop.height * frame.height / scale).roundToDouble()),
  );
}

/// Frame point sampled for output pixel ([u], [v]), taken at its centre.
Offset outputToFrame(double u, double v, Size source, PageEdit edit) {
  final frame = rotatedSize(source, edit.quarterTurns);
  final scale = coverScale(frame, edit.straightenDegrees * math.pi / 180);
  return Offset(
    edit.crop.left * frame.width + (u + 0.5) * scale,
    edit.crop.top * frame.height + (v + 0.5) * scale,
  );
}

/// Moves one crop corner to [point] (normalised frame coordinates), keeping
/// the opposite corner fixed and the crop inside the frame and at least
/// [PageEdit.minCropFraction] on each side.
Rect dragCropCorner(Rect crop, Alignment corner, Offset point) {
  const minSide = PageEdit.minCropFraction;
  var left = crop.left;
  var top = crop.top;
  var right = crop.right;
  var bottom = crop.bottom;
  if (corner.x < 0) {
    left = point.dx.clamp(0.0, right - minSide);
  } else {
    right = point.dx.clamp(left + minSide, 1.0);
  }
  if (corner.y < 0) {
    top = point.dy.clamp(0.0, bottom - minSide);
  } else {
    bottom = point.dy.clamp(top + minSide, 1.0);
  }
  return Rect.fromLTRB(left, top, right, bottom);
}
