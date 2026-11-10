import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/processing_status.dart';
import '../../routes/app_routes.dart';
import '../../state/export_providers.dart';
import '../../services/score_upload_api.dart';
import '../../state/processing_providers.dart';
import '../../state/score_upload_providers.dart';
import '../../state/session_actions.dart';
import '../../theme/app_theme.dart';
import '../../widgets/notification_ask.dart';
import '../../widgets/primary_pill_button.dart';
import '../../services/score_library_api.dart';
import '../../state/score_library_providers.dart';
import '../capture/capture_messages.dart';
import '../library/library_messages.dart';
import '../library/widgets/delete_score_dialog.dart';
import '../retake/rephotograph.dart';
import '../scan_status/scan_status_messages.dart';
import 'cancel_scan_dialog.dart';
import 'processing_messages.dart';

/// Processing View (PIYA-207, SOW Module 2): follows one job through the
/// pipeline and opens Playback when it's done.
///
/// The progress itself lives in [processingJobsProvider], not here, so
/// leaving this screen ("Convert in Background", the back arrow, system
/// Back) never stops the job being followed.
///
/// Four outcomes look and act differently, because each needs a different
/// thing from the user: a page that can be retaken (AC5/AC7), a layout
/// that can't be fixed by retaking (AC6/AC7), connection trouble (wait or
/// Retry), and an expired session (log in).
///
/// Opened straight from "Create score" it has no [jobId] yet: it shows the
/// upload owned by [scoreUploadsProvider] under [clientSubmissionId], and
/// switches to following the job in place once the 202 names it.
class ProcessingScreen extends ConsumerStatefulWidget {
  const ProcessingScreen({
    super.key,
    required this.jobId,
    required this.title,
    this.clientSubmissionId,
  });

  final String? jobId;

  /// The upload's key in [scoreUploadsProvider]; null when opened for a
  /// job that already exists.
  final String? clientSubmissionId;

  /// The score's title, carried to Playback and to a retake.
  final String title;

  /// AC8 asks for Playback within 2 s of completion; the 100% card shows
  /// for this long first so the user sees it finished (mockup 3).
  static const Duration completionHold = Duration(milliseconds: 1200);

  /// How long the bar and percentage take to catch up with a new value.
  static const Duration percentTween = Duration(milliseconds: 600);

  @override
  ConsumerState<ProcessingScreen> createState() => _ProcessingScreenState();
}

class _ProcessingScreenState extends ConsumerState<ProcessingScreen> {
  /// True once this screen has shown the job still running. A job that's
  /// already complete when the screen opens goes straight to Playback;
  /// one that finishes in view shows 100% first.
  bool _sawProgress = false;

  /// Set while the cancel dialog is open or the cancel request is in
  /// flight, so a completion arriving meanwhile can't navigate out from
  /// under the dialog (it's handled once the cancel settles).
  bool _cancelling = false;
  bool _cancelRequestInFlight = false;

  /// Set once this screen has started leaving, so it never navigates twice.
  bool _leaving = false;

  /// [_finish] is running (AC11 offer pending or being decided).
  bool _finishing = false;
  Timer? _completionTimer;

  /// The failure view's Delete request is in flight.
  bool _deleting = false;

  static const double _maxHeadingScale = 1.5;
  static const double _maxCardScale = 1.3;
  static const double _gutterFraction = 0.107; // 44 dp on the 412 dp mockup
  static const double _minGutter = 16;
  static const double _maxGutter = 44;
  static const int _fullPercent = 100;

  /// Read in initState: dispose can't use ref.
  late final ScoreUploadsController _uploads = ref.read(
    scoreUploadsProvider.notifier,
  );

  /// Null while the upload that makes the job is still sending.
  late String? _jobId = widget.jobId ?? _upload?.jobId;

  ScoreUpload? get _upload => switch (widget.clientSubmissionId) {
    final key? => ref.read(scoreUploadsProvider)[key],
    null => null,
  };

  /// Only called once [_jobId] is set.
  String get _id => _jobId!;

  @override
  void initState() {
    super.initState();
    _uploads;
    // Providers can't change while this widget is building.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (_jobId != null) {
        _follow();
      } else if (_upload == null) {
        // The upload is gone (nothing to show): the library has the row.
        _backToLibrary();
      } else {
        // It may have ended before the first build started listening.
        _onUpload(_upload);
      }
    });
  }

  void _follow() {
    ref.read(processingJobsProvider.notifier).track(_id, title: widget.title);
    final job = ref.read(processingJobsProvider)[_id];
    if (job != null) _react(job);
  }

  @override
  void dispose() {
    _completionTimer?.cancel();
    if (widget.clientSubmissionId case final key?) {
      // Not inside the tree teardown that is disposing this screen.
      scheduleMicrotask(() => _uploads.release(key));
    }
    super.dispose();
  }

  TrackedJob? get _job => ref.read(processingJobsProvider)[_jobId];

  void _onUpload(ScoreUpload? upload) {
    if (upload == null || _leaving) return;
    if (upload.jobId case final jobId? when _jobId == null) {
      // The 202: from here on this is the ordinary Processing view.
      setState(() {
        _jobId = jobId;
        _cancelRequestInFlight = false;
      });
      scheduleMicrotask(() {
        if (mounted) _follow();
      });
    } else if (upload.phase == UploadPhase.cancelled) {
      scheduleMicrotask(() {
        if (mounted) _backToEdit(cancelled: true);
      });
    } else if (upload.phase == UploadPhase.failed && _cancelRequestInFlight) {
      // The cancel lost the race to a failure: "Try again" must start fresh.
      setState(() => _cancelRequestInFlight = false);
    }
  }

  /// "Cancel sending": same as it was on Capture. The abort ends the
  /// upload as cancelled, which takes the user back to the pages.
  void _cancelUpload() {
    final key = widget.clientSubmissionId;
    if (key == null || _leaving || _cancelRequestInFlight) return;
    setState(() => _cancelRequestInFlight = true);
    _uploads.cancel(key);
  }

  /// "Back to edit pages", or a cancelled upload: Capture again, with the
  /// same pages, the error and the id the next send must use.
  void _backToEdit({bool cancelled = false}) {
    final key = widget.clientSubmissionId;
    if (key == null || _leaving) return;
    final upload = _uploads.takeForEdit(key);
    if (upload == null) return;
    _leaving = true;
    final messenger = ScaffoldMessenger.of(context);
    Navigator.of(context).pushReplacementNamed(
      AppRoutes.capturePages,
      arguments: CapturePagesArguments(
        details: upload.details,
        wholeRetake: upload.wholeRetake,
        resume: upload,
      ),
    );
    if (cancelled) {
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(
          const SnackBar(
            content: Text(CaptureMessages.uploadCancelled),
            duration: AppTheme.snackBarDuration,
          ),
        );
    }
  }

  /// A failed upload no resend can fix (dead retake, score limit): to the
  /// library, which reloads to show where things really stand.
  void _abandonUpload() {
    final upload = _upload;
    final retakeJobId = upload?.wholeRetake?.replacesJobId;
    final error = upload?.error;
    if (retakeJobId != null &&
        error is UploadRejectedException &&
        error.code == jobNotFoundCode) {
      ref.read(processingJobsProvider.notifier).forget(retakeJobId);
    }
    ref.invalidate(scoreLibraryProvider);
    _backToLibrary();
  }

  void _react(TrackedJob job) {
    if (_leaving) return;
    // PIYA-218 AC6: watched to the end here, so the bell has nothing new
    // to tell about it.
    if (job.isFinished &&
        !job.read &&
        (ModalRoute.of(context)?.isCurrent ?? false)) {
      ref.read(processingJobsProvider.notifier).markRead(job.jobId);
    }
    switch (job.phase) {
      case TrackedPhase.complete:
        if (!_cancelling) _complete(hold: _sawProgress);
      case TrackedPhase.sessionExpired:
        unawaited(_returnToLogin());
      case TrackedPhase.active ||
          TrackedPhase.reconnecting ||
          TrackedPhase.paused:
        if (job.status != null) _sawProgress = true;
      case TrackedPhase.failed ||
          TrackedPhase.cancelled ||
          TrackedPhase.notFound:
        // Shown in place by build().
        break;
    }
  }

  /// AC8: on to Playback, after [ProcessingScreen.completionHold] when the
  /// user watched it finish.
  void _complete({required bool hold}) {
    if (_leaving || _completionTimer != null) return;
    if (!hold) {
      unawaited(_finish());
      return;
    }
    _completionTimer = Timer(
      ProcessingScreen.completionHold,
      () => unawaited(_finish()),
    );
  }

  /// PIYA-207 AC8/AC11: with an `unreadable` voice the Re-photograph offer
  /// comes first (once per job), and routing waits for the answer. Only
  /// `render_failed` voices go straight to Playback.
  Future<void> _finish() async {
    // Set before the first await: a second `complete` (a poll landing
    // while the prefs are read) must not show the offer twice.
    if (!mounted || _leaving || _finishing) return;
    _finishing = true;
    final status = _job?.status;
    final unreadable = status?.unreadableVoices ?? const [];
    if (status == null ||
        unreadable.isEmpty ||
        await RephotographOfferPrefs.isAnswered(_id)) {
      _openPlayback();
      return;
    }
    if (!mounted || _leaving) return;
    _leaving = true;
    final navigator = Navigator.of(context);
    final choice = await showRephotographOffer(
      context,
      voices: unreadable,
      playable: status.playableVoiceCount,
    );
    if (!mounted) return;
    switch (choice) {
      case null:
        // System Back: to the library, not answered, offered again on
        // the next tap of the card (AC11).
        _goToLibrary(navigator);
      case RephotographChoice.continuePlayback:
        await RephotographOfferPrefs.markAnswered(_id);
        _leaving = false;
        _finishing = false;
        _openPlayback();
      case RephotographChoice.rephotograph:
        await RephotographOfferPrefs.markAnswered(_id);
        if (!mounted) return;
        await startWholeRetake(
          context,
          ref,
          jobId: _id,
          title: widget.title,
          details: status.details,
          // A retake of a retake keeps pointing at the score's card.
          retakeOfScoreId: status.scoreId ?? _job?.retakeOfScoreId,
        );
    }
  }

  void _openPlayback() {
    if (!mounted || _leaving) return;
    _leaving = true;
    final scoreId = _job?.libraryScoreId;
    final navigator = Navigator.of(context);
    if (scoreId == null) {
      // PIYA-102 doesn't return a scoreId yet (contract gap): the score is
      // in the library, so send the user there rather than strand them.
      _snack(ProcessingMessages.readyInLibrary);
      _goToLibrary(navigator);
      return;
    }
    navigator.pushReplacementNamed(
      AppRoutes.playback,
      arguments: PlaybackArguments(scoreId: scoreId, title: widget.title),
    );
  }

  /// "Convert in Background", the back arrow and system Back all land
  /// here. The job stays tracked.
  void _backToLibrary() {
    if (_leaving) return;
    _leaving = true;
    _completionTimer?.cancel();
    _goToLibrary(Navigator.of(context));
  }

  /// The back arrow and system back. While the scan still runs, leaving
  /// sends it to the background just as the button does, so it asks for
  /// notifications the same way (review M7, PIYA-218 AC11: "the first time
  /// a scan is sent to the background").
  void _leave() {
    if (_jobId == null) {
      // Back is blocked while sending, as it was on Capture: a send that
      // failed with no screen left would lose the pages (review N2).
      if (_upload?.phase != UploadPhase.sending) _backToLibrary();
      return;
    }
    final job = ref.read(processingJobsProvider)[_jobId];
    if (job != null && job.isRunning) {
      unawaited(_convertInBackground());
    } else {
      _backToLibrary();
    }
  }

  /// "Convert in Background" (PIYA-218): on Android 13+ the "it's ready"
  /// notification needs the user's yes, asked once here unless an export
  /// already asked. Leaving is decided before the dialog, so a finish
  /// while it is open doesn't move this screen under it; the library's
  /// card and bell show the result.
  Future<void> _convertInBackground() async {
    if (_leaving) return;
    _leaving = true;
    _completionTimer?.cancel();
    final navigator = Navigator.of(context);
    await askForNotificationsOnce(
      context,
      ref.read(notificationPermissionProvider),
      title: ScanStatusMessages.notificationsTitle,
      body: ScanStatusMessages.notificationsBody,
      later: ScanStatusMessages.notificationsLater,
      allow: ScanStatusMessages.notificationsAllow,
    );
    if (!mounted) return;
    _goToLibrary(navigator);
  }

  /// Pops back to the library already under this screen; if there isn't
  /// one (opened some other way), replaces this screen with it.
  static void _goToLibrary(NavigatorState navigator) {
    var found = false;
    navigator.popUntil((route) {
      if (route.settings.name == AppRoutes.scoreLibrary) {
        found = true;
        return true;
      }
      return route.isFirst;
    });
    if (!found) navigator.pushReplacementNamed(AppRoutes.scoreLibrary);
  }

  Future<void> _returnToLogin() async {
    if (_leaving) return;
    _leaving = true;
    _completionTimer?.cancel();
    final navigator = Navigator.of(context);
    await endLocalSession(ref);
    _snack(
      _jobId == null
          ? ProcessingMessages.sessionExpiredUpload
          : ProcessingMessages.sessionExpired,
    );
    navigator.pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  Future<void> _confirmCancel() async {
    if (_cancelling || _leaving) return;
    setState(() => _cancelling = true);
    final confirmed = await confirmCancelScan(context);
    if (!mounted) return;
    if (!confirmed) {
      setState(() => _cancelling = false);
      // It may have finished while the dialog was open.
      if (_job case final job?) _react(job);
      return;
    }
    setState(() => _cancelRequestInFlight = true);
    final outcome = await ref.read(processingJobsProvider.notifier).cancel(_id);
    if (!mounted) return;
    setState(() {
      _cancelling = false;
      _cancelRequestInFlight = false;
    });
    switch (outcome) {
      case CancelOutcome.cancelled:
        _snack(ProcessingMessages.scanCancelled);
        _backToLibrary();
      case CancelOutcome.notFound:
        _backToLibrary();
      case CancelOutcome.sessionExpired:
        await _returnToLogin();
      case CancelOutcome.failed:
        // The job may have finished while the dialog was open or the
        // request was out. _react was skipped then (cancelling), and the
        // tracker has stopped polling a finished job, so nothing else
        // would ever move this screen on from 100%.
        final job = _job;
        final finished =
            job != null &&
            (job.phase == TrackedPhase.complete ||
                job.phase == TrackedPhase.failed);
        _snack(
          finished
              ? ProcessingMessages.alreadyFinished
              : ProcessingMessages.cancelFailed,
        );
        if (job != null) _react(job);
      case CancelOutcome.alreadyFinished:
        // The tracker has re-polled: complete goes on to Playback, failed
        // shows its view.
        _snack(ProcessingMessages.alreadyFinished);
        if (_job case final job?) {
          _sawProgress = true;
          _react(job);
        }
    }
  }

  /// PIYA-207 AC7 `incompleteVoiceSequence`: the whole score (AC12). The
  /// failed scan's card is replaced by the new one, so no score id.
  void _retakeWhole() {
    if (_leaving) return;
    _leaving = true;
    unawaited(
      startWholeRetake(
        context,
        ref,
        jobId: _id,
        title: widget.title,
        details: _job?.status?.details,
      ),
    );
  }

  /// PIYA-218 AC3: Delete on the failure view, confirmed first, then
  /// PIYA-309. Only offered for the failed scan's own card: a failed
  /// retake of a completed score leaves that score as it was (PIYA-207
  /// AC12), so deleting from here would remove the good version.
  int? get _deletableScoreId {
    final job = _job;
    if (job == null || job.retakeOfScoreId != null) return null;
    return job.libraryScoreId;
  }

  Future<void> _deleteScan() async {
    final scoreId = _deletableScoreId;
    if (scoreId == null || _leaving || _deleting) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => DeleteScoreDialog(title: widget.title),
    );
    if (confirmed != true || !mounted || _leaving) return;
    setState(() => _deleting = true);
    String? failure;
    try {
      await ref.read(scoreLibraryProvider.notifier).deleteOnServer(scoreId);
    } on ScoreNotFoundException {
      // Already gone: the outcome the user asked for.
    } on SessionExpiredException {
      if (mounted) setState(() => _deleting = false);
      await _returnToLogin();
      return;
    } on ScoreLibraryNetworkException {
      failure = LibraryMessages.deleteNetworkError;
    } on Object catch (e) {
      debugPrint('Failed scan delete failed: $e');
      failure = LibraryMessages.deleteServerError;
    }
    if (!mounted) return;
    setState(() => _deleting = false);
    if (failure != null) {
      _snack(failure);
      return;
    }
    ref.read(processingJobsProvider.notifier)
      ..forgetScore(scoreId)
      ..forget(_id);
    _snack(LibraryMessages.deleted(widget.title));
    _backToLibrary();
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(content: Text(message), duration: AppTheme.snackBarDuration),
      );
  }

  /// The upload step: bytes sent, then the failure view if it fails.
  Widget _uploadBody(ScoreUpload? upload) {
    final error = upload?.error;
    if (upload != null && error != null) {
      final key = upload.key;
      final (String, VoidCallback)? primary = switch (error) {
        UploadSessionExpiredException() => (
          CaptureMessages.logIn,
          () => unawaited(_returnToLogin()),
        ),
        _
            when upload.wholeRetake != null &&
                CaptureMessages.isDeadWholeRetake(error) =>
          (CaptureMessages.backToLibrary, _abandonUpload),
        UploadRejectedException(isScoreLimit: true) => (
          CaptureMessages.library,
          _abandonUpload,
        ),
        // Fixed on the pages or the details, not by sending again.
        UploadFileMissingException() => null,
        _ when CaptureMessages.isDetailsError(error) => null,
        _ => (ProcessingMessages.retry, () => _uploads.retry(key)),
      };
      return _FailureView(
        heading: ProcessingMessages.uploadFailedHeading,
        body: error is UploadRejectedException && error.isScoreLimit
            ? CaptureMessages.scoreLimitBody
            : (upload.wholeRetake != null
                      ? CaptureMessages.wholeRetakeError(error)
                      : null) ??
                  CaptureMessages.uploadError(error),
        onBack: _backToLibrary,
        primary: primary,
        onBackToEdit: _backToEdit,
      );
    }
    final sent = upload?.sent ?? 0;
    final total = upload?.total ?? 0;
    final percent = total > 0
        ? (sent * _fullPercent ~/ total).clamp(0, _fullPercent)
        : 0;
    final session = upload?.session;
    final pages = session == null || session.hasPdf ? 0 : session.pageCount;
    // shortcut: the page is read off the byte count as if every page were
    // the same size; use per-part offsets if users notice it jump.
    final page = math.min(pages, total == 0 ? 1 : sent * pages ~/ total + 1);
    return _ProgressView(
      subtitle: total > 0 && sent >= total
          ? ProcessingMessages.uploadChecking
          : pages == 0
          ? ProcessingMessages.uploadingPdf
          : ProcessingMessages.uploadingPage(page, pages),
      percent: percent,
      cardLabel: ProcessingMessages.uploadSemantics(percent),
      helper: ProcessingMessages.uploadHelper,
      cancelLabel: _cancelRequestInFlight
          ? ProcessingMessages.cancelling
          : ProcessingMessages.cancelUpload,
      cancelling: _cancelRequestInFlight,
      onCancel: upload == null || _leaving ? null : _cancelUpload,
      // Pages leave the phone only on a 202; the user stays until then.
      onBackground: null,
      headingScale: _maxHeadingScale,
      cardScale: _maxCardScale,
    );
  }

  Widget _jobProgress(TrackedJob? job) {
    final status = job?.status;
    final phase = job?.phase ?? TrackedPhase.active;
    final percent = job?.percent ?? 0;
    final current = status?.currentPage;
    final total = status?.totalPages;
    final showPage = current != null && total != null;
    final seconds =
        status?.stage != ProcessingStage.complete &&
            phase != TrackedPhase.complete
        ? status?.estimatedRemainingSeconds
        : null;
    return _ProgressView(
      subtitle: ProcessingMessages.subtitle(status?.stage),
      percent: percent,
      pageText: showPage ? ProcessingMessages.page(current, total) : null,
      secondsLeft: seconds,
      cardLabel: ProcessingMessages.cardSemantics(
        percent: percent,
        currentPage: showPage ? current : null,
        totalPages: showPage ? total : null,
        secondsLeft: seconds,
      ),
      helper: switch (phase) {
        TrackedPhase.reconnecting => ProcessingMessages.reconnecting,
        _ when job?.isStalled ?? false => ProcessingMessages.stalled,
        _ => ProcessingMessages.helper,
      },
      onRetry: phase == TrackedPhase.paused
          ? () => ref.read(processingJobsProvider.notifier).retry(_id)
          : null,
      cancelLabel: _cancelRequestInFlight
          ? ProcessingMessages.cancelling
          : ProcessingMessages.cancelScan,
      cancelling: _cancelRequestInFlight,
      onCancel: job?.phase == TrackedPhase.complete || _leaving
          ? null
          : _confirmCancel,
      onBackground: () => unawaited(_convertInBackground()),
      headingScale: _maxHeadingScale,
      cardScale: _maxCardScale,
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<TrackedJob?>(
      processingJobsProvider.select((jobs) => jobs[_jobId]),
      (_, next) {
        if (next != null) _react(next);
      },
    );
    final job = ref.watch(
      processingJobsProvider.select((jobs) => jobs[_jobId]),
    );
    final uploadKey = widget.clientSubmissionId;
    ScoreUpload? upload;
    if (uploadKey != null) {
      ref.listen<ScoreUpload?>(
        scoreUploadsProvider.select((uploads) => uploads[uploadKey]),
        (_, next) => _onUpload(next),
      );
      upload = ref.watch(
        scoreUploadsProvider.select((uploads) => uploads[uploadKey]),
      );
    }
    final width = MediaQuery.sizeOf(context).width;
    final gutter = (width * _gutterFraction).clamp(_minGutter, _maxGutter);

    final Widget body = switch (job?.phase) {
      _ when _jobId == null => _uploadBody(upload),
      TrackedPhase.failed => _FailureView(
        heading:
            job?.status?.failureReason == FailureReason.unsupportedStaffLayout
            ? ProcessingMessages.unsupportedHeading
            : ProcessingMessages.failedHeading,
        status: job!.status,
        onRetakeWhole: _retakeWhole,
        onBack: _backToLibrary,
        onDelete: _deletableScoreId == null ? null : _deleteScan,
        deleting: _deleting,
      ),
      TrackedPhase.notFound => _FailureView(
        heading: ProcessingMessages.notFoundHeading,
        body: ProcessingMessages.notFoundBody,
        onBack: _backToLibrary,
      ),
      TrackedPhase.cancelled => _FailureView(
        heading: ProcessingMessages.cancelledHeading,
        body: ProcessingMessages.cancelledBody,
        onBack: _backToLibrary,
      ),
      _ => _jobProgress(job),
    };

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _leave();
      },
      child: Scaffold(
        backgroundColor: Colors.white,
        body: SafeArea(
          child: CustomScrollView(
            slivers: [
              SliverFillRemaining(
                hasScrollBody: false,
                child: Padding(
                  padding: EdgeInsets.fromLTRB(gutter, 4, gutter, 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Align(
                        alignment: Alignment.centerLeft,
                        child: IconButton(
                          tooltip: ProcessingMessages.backToLibrary,
                          onPressed:
                              _jobId == null &&
                                  _upload?.phase == UploadPhase.sending
                              ? null
                              : _leave,
                          color: AppTheme.onboardingHeadingDark,
                          icon: const Icon(Icons.arrow_back_rounded),
                        ),
                      ),
                      Expanded(child: body),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The upload step and the job's progress share this layout; the caller
/// words it.
class _ProgressView extends StatelessWidget {
  const _ProgressView({
    required this.subtitle,
    required this.percent,
    required this.cardLabel,
    required this.helper,
    required this.cancelLabel,
    required this.cancelling,
    required this.onCancel,
    required this.onBackground,
    required this.headingScale,
    required this.cardScale,
    this.pageText,
    this.secondsLeft,
    this.onRetry,
  });

  final String subtitle;
  final int percent;
  final String cardLabel;
  final String? pageText;
  final int? secondsLeft;
  final String helper;

  /// Set while polling is paused: the Retry panel replaces [helper].
  final VoidCallback? onRetry;
  final String cancelLabel;
  final bool cancelling;
  final VoidCallback? onCancel;
  /// Null hides "Convert in Background" (the upload step, see [_leave]).
  final VoidCallback? onBackground;
  final double headingScale;
  final double cardScale;

  static const double _cancelFontSize = 18;
  static const double _buttonMinHeight = 48;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final retry = onRetry;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Spacer(flex: 5),
        MediaQuery.withClampedTextScaling(
          maxScaleFactor: headingScale,
          child: Semantics(
            header: true,
            child: Text(
              ProcessingMessages.heading,
              style: textTheme.headlineSmall?.copyWith(
                fontSize: 26,
                fontWeight: FontWeight.w700,
                color: AppTheme.onboardingHeadingDark,
              ),
            ),
          ),
        ),
        // Live, so a screen reader hears each stage change, but not every
        // percentage tick (that's in the card's label).
        Semantics(
          liveRegion: true,
          child: Text(
            subtitle,
            style: textTheme.titleMedium?.copyWith(
              fontSize: 18,
              fontWeight: FontWeight.w400,
              color: AppTheme.onboardingBody,
            ),
          ),
        ),
        const SizedBox(height: 12),
        MediaQuery.withClampedTextScaling(
          maxScaleFactor: headingScale,
          child: _ProgressCard(
            percent: percent,
            label: cardLabel,
            pageText: pageText,
            secondsLeft: secondsLeft,
            percentScale: cardScale,
          ),
        ),
        const SizedBox(height: 8),
        if (retry != null)
          _PausedPanel(onRetry: retry)
        else
          Text(
            helper,
            textAlign: TextAlign.center,
            style: textTheme.bodySmall?.copyWith(
              fontSize: 11,
              color: AppTheme.onboardingBody,
            ),
          ),
        const Spacer(flex: 6),
        const SizedBox(height: 16),
        Center(
          child: TextButton.icon(
            onPressed: cancelling ? null : onCancel,
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.processingCancel,
              minimumSize: const Size(_buttonMinHeight, _buttonMinHeight),
              textStyle: textTheme.titleMedium?.copyWith(
                fontSize: _cancelFontSize,
                fontWeight: FontWeight.w500,
              ),
            ),
            icon: const Icon(Icons.close_rounded),
            label: Text(cancelLabel),
          ),
        ),
        if (onBackground != null) ...[
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: onBackground,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.processingSecondary,
              side: const BorderSide(color: AppTheme.processingSecondary),
              minimumSize: const Size.fromHeight(_buttonMinHeight),
              shape: const StadiumBorder(),
              textStyle: textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w600,
              ),
            ),
            child: const Text(
              ProcessingMessages.convertInBackground,
              textAlign: TextAlign.center,
            ),
          ),
        ],
      ],
    );
  }
}

/// The gradient card from the mockups: big percentage, page and time left,
/// and the bar.
class _ProgressCard extends StatelessWidget {
  const _ProgressCard({
    required this.percent,
    required this.label,
    required this.pageText,
    required this.secondsLeft,
    required this.percentScale,
  });

  final int percent;

  /// Read when the card is focused, so a tick isn't announced each time.
  final String label;
  final String? pageText;
  final int? secondsLeft;
  final double percentScale;

  static const double _radius = 10;
  static const double _trackHeight = 4;
  static const double _percentFontSize = 40;
  static const double _pageFontSize = 12;
  static const double _etaFontSize = 13;
  static const double _maxPercent = 100;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final page = pageText;
    final seconds = secondsLeft;

    return Semantics(
      container: true,
      label: label,
      child: ExcludeSemantics(
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: AppTheme.processingCardGradient,
            borderRadius: BorderRadius.circular(_radius),
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            child: TweenAnimationBuilder<double>(
              tween: Tween<double>(end: percent.toDouble()),
              duration: ProcessingScreen.percentTween,
              curve: Curves.easeOut,
              builder: (context, value, _) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      MediaQuery.withClampedTextScaling(
                        maxScaleFactor: percentScale,
                        child: Text(
                          ProcessingMessages.percent(value.round()),
                          style: textTheme.displaySmall?.copyWith(
                            fontSize: _percentFontSize,
                            fontWeight: FontWeight.w700,
                            color: Colors.white,
                            height: 1.2,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            if (page != null)
                              Text(
                                page,
                                textAlign: TextAlign.end,
                                style: textTheme.labelSmall?.copyWith(
                                  fontSize: _pageFontSize,
                                  fontWeight: FontWeight.w700,
                                  color: AppTheme.processingPageText,
                                ),
                              ),
                            if (seconds != null)
                              Text(
                                ProcessingMessages.timeLeft(seconds),
                                textAlign: TextAlign.end,
                                style: textTheme.labelMedium?.copyWith(
                                  fontSize: _etaFontSize,
                                  fontWeight: FontWeight.w600,
                                  color: Colors.white,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  LinearProgressIndicator(
                    value: value / _maxPercent,
                    minHeight: _trackHeight,
                    color: Colors.white,
                    backgroundColor: AppTheme.processingTrack,
                    borderRadius: BorderRadius.circular(_trackHeight / 2),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Spec §7 "No internet": after [ProcessingTiming.pauseAfter] of failed
/// polls, stop implying progress and hand the user a Retry.
class _PausedPanel extends StatelessWidget {
  const _PausedPanel({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Semantics(
      liveRegion: true,
      container: true,
      child: Column(
        children: [
          const Icon(Icons.wifi_off_rounded, color: AppTheme.onboardingBody),
          const SizedBox(height: 4),
          Text(
            ProcessingMessages.pausedTitle,
            textAlign: TextAlign.center,
            style: textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppTheme.onboardingHeadingDark,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            ProcessingMessages.pausedBody,
            textAlign: TextAlign.center,
            style: textTheme.bodySmall?.copyWith(
              color: AppTheme.onboardingBody,
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: onRetry,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.processingSecondary,
              side: const BorderSide(color: AppTheme.processingSecondary),
              minimumSize: const Size(48, 48),
              shape: const StadiumBorder(),
            ),
            icon: const Icon(Icons.refresh_rounded),
            label: const Text(ProcessingMessages.retry),
          ),
        ],
      ),
    );
  }
}

/// AC5–AC7: replaces the progress view entirely, so a failure never reads
/// as "still loading". Copy is per reason; actions depend on whether a
/// retake can help.
class _FailureView extends StatelessWidget {
  const _FailureView({
    required this.heading,
    required this.onBack,
    this.status,
    this.body,
    this.onRetakeWhole,
    this.onDelete,
    this.deleting = false,
    this.primary,
    this.onBackToEdit,
  });

  final String heading;
  final ProcessingStatus? status;

  /// Upload failures: the main action (e.g. "Try again"), above "Back to
  /// edit pages".
  final (String, VoidCallback)? primary;

  /// Upload failures: back to Capture with the same pages.
  final VoidCallback? onBackToEdit;

  /// Fixed copy for the non-pipeline cases (gone, cancelled); otherwise
  /// worded from [status].
  final String? body;

  /// AC7/AC12: re-photograph the whole score. Page-specific failures use
  /// this too: there is no per-page resubmit route (planned PIYA-116).
  final VoidCallback? onRetakeWhole;
  final VoidCallback onBack;

  /// PIYA-218 AC3: removes the failed scan's score; null hides it.
  final VoidCallback? onDelete;
  final bool deleting;

  static const double _iconSize = 48;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final reason = status?.failureReason ?? FailureReason.unknown;
    // PIYA-102 `pageIndex` is assumed to count from 0 like PIYA-101's
    // (open contract question, PIYA-216); people count from 1.
    final pageIndex = status?.failedPageIndex;
    final page = pageIndex == null ? null : pageIndex + 1;
    final canRetakeWhole =
        body == null &&
        (reason.isRetakeable || reason.isWholeRetakeable) &&
        onRetakeWhole != null;
    final unsupported = reason == FailureReason.unsupportedStaffLayout;
    final edit = onBackToEdit == null
        ? null
        : (ProcessingMessages.backToEditPages, onBackToEdit!);
    const library = ProcessingMessages.backToLibrary;
    final (String, VoidCallback) main;
    final (String, VoidCallback)? second;
    if (canRetakeWhole) {
      main = (RephotographMessages.rephotograph, onRetakeWhole!);
      second = (library, onBack);
    } else if (primary != null) {
      main = primary!;
      second = edit ?? (library, onBack);
    } else if (edit != null) {
      main = edit;
      second = (library, onBack);
    } else {
      main = (library, onBack);
      second = null;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Spacer(flex: 3),
        Icon(
          unsupported
              ? Icons.view_stream_outlined
              : Icons.error_outline_rounded,
          size: _iconSize,
          color: AppTheme.errorRed,
        ),
        const SizedBox(height: 12),
        MediaQuery.withClampedTextScaling(
          maxScaleFactor: 1.5,
          child: Semantics(
            header: true,
            child: Text(
              heading,
              textAlign: TextAlign.center,
              style: textTheme.headlineSmall?.copyWith(
                fontSize: 24,
                fontWeight: FontWeight.w700,
                color: AppTheme.onboardingHeadingDark,
              ),
            ),
          ),
        ),
        const SizedBox(height: 12),
        Semantics(
          liveRegion: true,
          child: Text(
            body ?? ProcessingMessages.failureBody(reason, page),
            textAlign: TextAlign.center,
            style: textTheme.bodyLarge?.copyWith(
              color: AppTheme.onboardingBody,
            ),
          ),
        ),
        if (body == null && unsupported && page != null) ...[
          const SizedBox(height: 8),
          Text(
            ProcessingMessages.foundOnPage(page),
            textAlign: TextAlign.center,
            style: textTheme.bodyMedium?.copyWith(
              color: AppTheme.onboardingBody,
            ),
          ),
        ],
        if (canRetakeWhole) ...[
          const SizedBox(height: 16),
          Text(
            ProcessingMessages.retakeTipsTitle,
            style: textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppTheme.onboardingHeadingDark,
            ),
          ),
          const SizedBox(height: 4),
          for (final tip in ProcessingMessages.retakeTips)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 2, right: 8),
                    child: Icon(
                      Icons.check_rounded,
                      size: 18,
                      color: AppTheme.processingSecondary,
                    ),
                  ),
                  Expanded(
                    child: Text(
                      tip,
                      style: textTheme.bodyMedium?.copyWith(
                        color: AppTheme.onboardingBody,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
        const Spacer(flex: 4),
        const SizedBox(height: 16),
        PrimaryPillButton(
          label: main.$1,
          onPressed: main.$2,
          // White on the brand blue is 4.3:1; this blue passes 4.5:1.
          backgroundColor: AppTheme.processingSecondary,
        ),
        if (second != null) ...[
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: second.$2,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.processingSecondary,
              side: const BorderSide(color: AppTheme.processingSecondary),
              minimumSize: const Size.fromHeight(48),
              shape: const StadiumBorder(),
            ),
            child: Text(second.$1),
          ),
        ],
        if (onDelete != null) ...[
          const SizedBox(height: 8),
          TextButton.icon(
            key: const ValueKey('failure-delete'),
            onPressed: deleting ? null : onDelete,
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.errorRed,
              minimumSize: const Size.fromHeight(48),
            ),
            icon: deleting
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: AppTheme.errorRed,
                      semanticsLabel: LibraryMessages.deleting,
                    ),
                  )
                : const Icon(Icons.delete_outline_rounded),
            label: const Text(ScanStatusMessages.deleteScan),
          ),
        ],
      ],
    );
  }
}
