import '../models/score_details.dart';
import '../models/score_upload.dart';
import '../models/whole_retake_arguments.dart';

export '../models/whole_retake_arguments.dart';

/// Named route constants. Onboarding itself is the app's `home` (not a
/// named route) since it's a one-time gate, not something re-navigated to.
class AppRoutes {
  AppRoutes._();

  static const login = '/login';
  static const signUp = '/sign-up';
  static const passwordReset = '/password-reset';
  static const scoreLibrary = '/library';

  // Destinations from the Score Library (PIYA-205 AC7/AC8). They route to
  // ComingSoon placeholders until PIYA-206/208/212 land; the route names
  // and arguments are the contract those screens must keep.
  static const playback = '/playback';
  static const capture = '/capture';
  static const settings = '/settings';

  // PIYA-206: [capture] opens step 1 (score details); step 2 takes the
  // pages, then hands the job to Processing (PIYA-207).
  static const capturePages = '/capture/pages';
  static const processing = '/processing';
}

/// Arguments for [AppRoutes.capturePages]: the step-1 answers that travel
/// with the pages at submit, and the whole-score retake they belong to.
/// [resume] is an upload that failed or was cancelled on Processing ("Back
/// to edit pages"): its pages, error and id come back to Capture.
class CapturePagesArguments {
  const CapturePagesArguments({
    required this.details,
    this.wholeRetake,
    this.resume,
  });

  final ScoreDetails details;
  final WholeRetakeArguments? wholeRetake;
  final ScoreUpload? resume;
}

/// Arguments for [AppRoutes.processing]. [jobId] is what Processing
/// (PIYA-207) polls; [title] is for its header while it loads. Straight
/// from "Create score" there is no job yet: [clientSubmissionId] names the
/// upload in [scoreUploadsProvider] that will produce it.
class ProcessingArguments {
  const ProcessingArguments({
    required this.jobId,
    required this.title,
    this.clientSubmissionId,
  }) : assert(jobId != null || clientSubmissionId != null);

  final String? jobId;
  final String title;
  final String? clientSubmissionId;
}

/// Arguments for [AppRoutes.playback]. Carries the id of an already
/// processed score, so Playback loads its existing audio rather than
/// re-running the pipeline (PIYA-205 AC7). [title] is only for the app bar
/// while Playback fetches the rest.
class PlaybackArguments {
  const PlaybackArguments({required this.scoreId, required this.title});

  final int scoreId;
  final String title;
}
