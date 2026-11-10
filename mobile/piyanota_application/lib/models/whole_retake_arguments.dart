import 'score_details.dart';

/// Arguments for [AppRoutes.capture] when it starts a whole-score retake
/// (PIYA-207 AC12): step 1 opens pre-filled with [details], and the submit
/// carries [replacesJobId]. [retakeOfScoreId] is the completed score the
/// retake will fill (null for a failed scan, whose card is replaced).
///
/// Lives in models (re-exported by app_routes) so state can use it without
/// importing the routes file.
class WholeRetakeArguments {
  const WholeRetakeArguments({
    required this.replacesJobId,
    required this.details,
    this.retakeOfScoreId,
  });

  final String replacesJobId;
  final ScoreDetails details;
  final int? retakeOfScoreId;
}
