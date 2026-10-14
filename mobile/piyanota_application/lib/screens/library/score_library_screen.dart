import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../models/score_summary.dart';
import '../../routes/app_routes.dart';
import '../../services/score_library_api.dart';
import '../../state/processing_providers.dart';
import '../../state/score_library_providers.dart';
import '../../state/session_actions.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import '../auth/widgets/auth_error_banner.dart';
import '../processing/cancel_scan_dialog.dart';
import '../processing/processing_messages.dart';
import '../scan_status/scan_navigation.dart';
import 'library_messages.dart';
import 'widgets/delete_score_dialog.dart';
import 'widgets/library_bottom_nav.dart';
import 'widgets/library_header.dart';
import 'widgets/score_cards.dart';

/// PIYA-205 — Score Library, the home screen after login.
///
/// It is reached with `pushNamedAndRemoveUntil`, so it is the only route on
/// the stack: Android back exits the app rather than returning to Login.
class ScoreLibraryScreen extends ConsumerStatefulWidget {
  const ScoreLibraryScreen({super.key});

  @override
  ConsumerState<ScoreLibraryScreen> createState() => _ScoreLibraryScreenState();
}

class _ScoreLibraryScreenState extends ConsumerState<ScoreLibraryScreen> {
  final _searchController = TextEditingController();
  String _query = '';

  /// Scores with a delete request in flight, or confirmed deleted and
  /// animating out. Their rows stay on screen (PIYA-215 AC2: removed only
  /// after the server confirms) with taps disabled.
  final Set<int> _deletingIds = {};

  /// Trash-path deletions the server has confirmed, playing their exit
  /// transition before leaving the list. (Swiped rows are animated out by
  /// Dismissible itself.)
  final Set<int> _leavingIds = {};

  /// Scores whose delete confirmation dialog is open, so a double tap on
  /// the trash can't stack a second dialog.
  final Set<int> _confirmingIds = {};

  /// True while a Playback route is being pushed, so a double tap on a card
  /// opens it once.
  bool _openingScore = false;

  /// Jobs whose long-press cancel dialog or request is in progress.
  final Set<String> _cancellingJobs = {};

  // Mockup: 32 dp side margins at 412 dp wide, header content at 26 dp,
  // first card 32 dp under the header, 18 dp between cards. Margins scale
  // down on narrow phones so cards keep usable text width.
  static const double _cardMarginFraction = 32 / 412;
  static const double _maxCardMargin = 32;
  static const double _minCardMargin = 16;
  static const double _headerInsetFromCards = 6;
  static const double _listTopGap = 32;
  static const double _cardGap = 18;
  static const double _stateMessageTopGap = 16;
  static const double _snackBarSideMargin = 16;
  static const double _swipeIconSize = 24;
  static const double _swipeIconInset = 24;
  static const double _swipeSpinnerSize = 20;
  static const double _swipeSpinnerStroke = 2;
  static const double _cardRadius = 12;
  static const Duration _swipeMoveDuration = Duration(milliseconds: 200);
  static const Duration _swipeResizeDuration = Duration(milliseconds: 220);

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  /// AC3: filters on every keystroke. PIYA-215 AC1 adds the debounce and a
  /// PIYA-308 call here; the screen only ever renders the filtered result.
  void _onSearchChanged(String value) => setState(() => _query = value);

  /// The tracked job a card follows instead of opening Playback (PIYA-218
  /// AC3): a scan still running (including a whole-score retake of a
  /// completed score, PIYA-207 AC12), or a scan that failed. A failed
  /// retake of a completed score doesn't count: that score is unchanged
  /// and plays as before.
  static TrackedJob? _cardJob(Map<String, TrackedJob> jobs, int scoreId) {
    final job = latestScanJobFor(jobs, scoreId);
    if (job == null) return null;
    if (job.isRunning) return job;
    if (job.phase == TrackedPhase.failed && job.retakeOfScoreId == null) {
      return job;
    }
    return null;
  }

  /// AC3 for a card whose scan is running or failed.
  Future<void> _openJob(TrackedJob job, String title) async {
    if (_openingScore) return;
    _openingScore = true;
    try {
      await openScanJob(Navigator.of(context), ref, job, title: title);
    } finally {
      _openingScore = false;
    }
  }

  /// PIYA-218 AC4: long-press "Cancel scan" on a processing card, with the
  /// same dialog and PIYA-114 call as Processing (PIYA-207 AC4).
  Future<void> _cancelScan(TrackedJob job) async {
    if (_cancellingJobs.contains(job.jobId)) return;
    _cancellingJobs.add(job.jobId);
    try {
      if (!await confirmCancelScan(context) || !mounted) return;
      final outcome = await ref
          .read(processingJobsProvider.notifier)
          .cancel(job.jobId);
      if (!mounted) return;
      switch (outcome) {
        case CancelOutcome.cancelled:
          _showSnackBar(ProcessingMessages.scanCancelled);
        case CancelOutcome.notFound:
          break;
        case CancelOutcome.sessionExpired:
          await _returnToLogin();
        case CancelOutcome.failed:
          _showSnackBar(ProcessingMessages.cancelFailed);
        case CancelOutcome.alreadyFinished:
          _showSnackBar(ProcessingMessages.alreadyFinished);
      }
    } finally {
      _cancellingJobs.remove(job.jobId);
    }
  }

  Future<void> _openScore(LibraryEntry entry) async {
    if (_openingScore) return;
    // PIYA-218 AC3 (and PIYA-207 AC12): a running or failed scan opens
    // Processing, never a Playback with nothing to play.
    final job = _cardJob(ref.read(processingJobsProvider), entry.scoreId);
    if (job != null) return _openJob(job, entry.displayTitle);
    _openingScore = true;
    // Moves the score to the top of the library now; the real server
    // records the open itself when Playback fetches it (PIYA-308 AC8).
    ref.read(scoreLibraryProvider.notifier).markOpened(entry.scoreId);
    try {
      // AC7: the existing score's id only — Playback loads its stored
      // audio; nothing here triggers processing.
      await Navigator.of(context).pushNamed(
        AppRoutes.playback,
        arguments: PlaybackArguments(
          scoreId: entry.scoreId,
          title: entry.displayTitle,
        ),
      );
    } finally {
      _openingScore = false;
    }
  }

  void _openCapture() => Navigator.of(context).pushNamed(AppRoutes.capture);

  void _openSettings() => Navigator.of(context).pushNamed(AppRoutes.settings);

  Future<void> _returnToLogin() async {
    await endLocalSession(ref);
    if (!mounted) return;
    Navigator.of(context)
        .pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  /// Confirm dialog, then the server delete. Shared by the trash icon and
  /// swipe-to-delete so both behave identically. Returns true only when the
  /// score is gone server-side — deleted (200), or already gone (404) — and
  /// the row may leave; on cancel or any other failure the row stays (and a
  /// swiped row snaps back).
  Future<bool> _deleteScore(LibraryEntry entry) async {
    final scoreId = entry.scoreId;
    if (_confirmingIds.contains(scoreId) || _deletingIds.contains(scoreId)) {
      return false;
    }
    _confirmingIds.add(scoreId);
    final bool? confirmed;
    try {
      // PIYA-309 AC5: the API deletes without asking, so confirmation is
      // ours.
      confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => DeleteScoreDialog(title: entry.displayTitle),
      );
    } finally {
      _confirmingIds.remove(scoreId);
    }
    if (confirmed != true || !mounted) return false;

    setState(() => _deletingIds.add(scoreId));
    String message;
    SnackBarAction? action;
    var gone = false;
    try {
      await ref.read(scoreLibraryProvider.notifier).deleteOnServer(scoreId);
      message = LibraryMessages.deleted(entry.displayTitle);
      gone = true;
    } on ScoreNotFoundException {
      message = LibraryMessages.deleteAlreadyGone;
      gone = true;
    } on SessionExpiredException {
      // Retrying can't fix a rejected token; give the way out right here.
      message = LibraryMessages.sessionExpired;
      action = SnackBarAction(
        label: LibraryMessages.logInAgain,
        onPressed: _returnToLogin,
      );
    } on ScoreLibraryNetworkException {
      message = LibraryMessages.deleteNetworkError;
    } on ScoreLibraryServerException {
      message = LibraryMessages.deleteServerError;
    } catch (e, stack) {
      // Anything unmapped still has to clear the row's spinner.
      if (kDebugMode) debugPrint('Score delete failed: $e\n$stack');
      message = LibraryMessages.deleteServerError;
    }
    // PIYA-218: a deleted score's scans leave the bell and the stored
    // history with it.
    if (gone) ref.read(processingJobsProvider.notifier).forgetScore(scoreId);
    if (!mounted) return gone;
    // A gone row keeps its disabled state until it has left the list.
    if (!gone) setState(() => _deletingIds.remove(scoreId));
    _showSnackBar(message, action: action);
    return gone;
  }

  /// [rowContext] belongs to the row that started the delete. If the row
  /// was unmounted while the request was in flight (e.g. a search hid it),
  /// its exit animation can never run, so the score is removed directly;
  /// otherwise a remounted row would keep its spinner forever.
  Future<void> _deleteViaTrash(
    LibraryEntry entry,
    BuildContext rowContext,
  ) async {
    final gone = await _deleteScore(entry);
    if (!gone || !mounted) return;
    if (rowContext.mounted) {
      setState(() => _leavingIds.add(entry.scoreId));
    } else {
      _finishRemoval(entry.scoreId);
    }
  }

  /// Swipe path of [_deleteViaTrash]. Dismissible only calls `onDismissed`
  /// if it is still mounted when `confirmDismiss` resolves, so a row hidden
  /// mid-request is removed here instead.
  Future<bool> _deleteViaSwipe(
    LibraryEntry entry,
    BuildContext rowContext,
  ) async {
    final gone = await _deleteScore(entry);
    if (gone && mounted && !rowContext.mounted) _finishRemoval(entry.scoreId);
    return gone;
  }

  void _finishRemoval(int scoreId) {
    if (!mounted) return;
    setState(() {
      _leavingIds.remove(scoreId);
      _deletingIds.remove(scoreId);
    });
    ref.read(scoreLibraryProvider.notifier).removeLocally(scoreId);
  }

  void _showSnackBar(String message, {SnackBarAction? action}) {
    final navHeight = LibraryBottomNav.heightFor(
      MediaQuery.paddingOf(context).bottom,
    );
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(message),
          action: action,
          behavior: SnackBarBehavior.floating,
          // Floats above the custom nav bar, which lives in the body and so
          // isn't known to Scaffold's own snackbar placement.
          margin: EdgeInsets.fromLTRB(
            _snackBarSideMargin,
            0,
            _snackBarSideMargin,
            navHeight,
          ),
        ),
      );
  }

  /// Reloads the list only when a finished scan changes which scores
  /// exist: a retake of a completed score that failed or was cancelled
  /// (PIYA-207 AC12, the old result is back), or a scan that completed as
  /// a score the list doesn't have yet. A scan that completes as a card
  /// already listed just turns into a normal card in place (PIYA-218
  /// AC4). The user hears about the outcome from the app-wide toast
  /// (AC7), which replaces this screen's old retake-failed snackbar.
  void _onJobsChanged(
    Map<String, TrackedJob>? previous,
    Map<String, TrackedJob> next,
  ) {
    final listed = {
      for (final score in ref.read(scoreLibraryProvider).value ?? const [])
        score.scoreId,
    };
    for (final job in next.values) {
      final before = previous?[job.jobId]?.phase;
      if (before == null || before == job.phase) continue;
      final retakeEnded =
          job.retakeOfScoreId != null &&
          (job.phase == TrackedPhase.failed ||
              job.phase == TrackedPhase.cancelled);
      final scoreId = job.libraryScoreId;
      final newScore =
          job.phase == TrackedPhase.complete &&
          (scoreId == null || !listed.contains(scoreId));
      if (retakeEnded || newScore) {
        ref.invalidate(scoreLibraryProvider);
        return;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(processingJobsProvider, _onJobsChanged);
    final library = ref.watch(scoreLibraryProvider);
    final jobs = ref.watch(processingJobsProvider);
    final width = MediaQuery.sizeOf(context).width;
    final cardMargin = (width * _cardMarginFraction)
        .clamp(_minCardMargin, _maxCardMargin)
        .toDouble();
    final navHeight = LibraryBottomNav.heightFor(
      MediaQuery.paddingOf(context).bottom,
    );
    final keyboardHeight = MediaQuery.viewInsetsOf(context).bottom;
    // Hidden while searching: on a small phone at large text the Add Score
    // card would push every result below the fold (NFR-10). The nav bar's
    // Capture button still covers AC8.
    final showAddCard = _query.trim().isEmpty;

    final subtitle = switch (library) {
      AsyncData(:final value) =>
        value.isEmpty
            ? LibraryMessages.emptySubtitle
            : LibraryMessages.scoreCountSubtitle(value.length),
      AsyncError() => LibraryMessages.errorSubtitle,
      _ => LibraryMessages.loadingSubtitle,
    };

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: AppTheme.libraryBackground,
        // The nav bar stays put behind the keyboard; the list pads by the
        // keyboard height instead so every result is still reachable.
        resizeToAvoidBottomInset: false,
        body: Stack(
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                LibraryHeader(
                  subtitle: subtitle,
                  searchController: _searchController,
                  onSearchChanged: _onSearchChanged,
                  horizontalPadding: cardMargin - _headerInsetFromCards,
                ),
                Expanded(
                  child: ListView(
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    padding: EdgeInsets.fromLTRB(
                      cardMargin,
                      // Without the Add card, the first result carries its
                      // own card gap; keep it where the Add card sat.
                      showAddCard ? _listTopGap : _listTopGap - _cardGap,
                      cardMargin,
                      (keyboardHeight > navHeight
                              ? keyboardHeight
                              : navHeight) +
                          _cardGap,
                    ),
                    children: [
                      if (showAddCard) AddScoreCard(onTap: _openCapture),
                      ..._buildStateContent(library, jobs),
                    ],
                  ),
                ),
              ],
            ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: LibraryBottomNav(
                // Library is this screen.
                onLibrary: () {},
                onCapture: _openCapture,
                onSettings: _openSettings,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// PIYA-218 AC2: a scan whose score the list doesn't show yet (the
  /// server didn't send its scoreId, or the list was loaded before the
  /// submit) still gets its processing card, above the saved scores.
  List<Widget> _unlistedScanCards(
    Map<String, TrackedJob> jobs,
    Set<int> listed,
  ) {
    final needle = _query.trim().toLowerCase();
    final running = [
      for (final job in jobs.values)
        if (job.isRunning &&
            (job.libraryScoreId == null ||
                !listed.contains(job.libraryScoreId)) &&
            (needle.isEmpty ||
                (job.title ?? untitledScoreLabel).toLowerCase().contains(
                  needle,
                )))
          job,
    ]..sort(compareScanJobsNewestFirst);
    return [
      for (final job in running)
        Padding(
          key: ValueKey('scan-job-${job.jobId}'),
          padding: const EdgeInsets.only(top: _cardGap),
          child: _scanningCard(job, job.title ?? untitledScoreLabel),
        ),
    ];
  }

  Widget _scanningCard(TrackedJob job, String title, {String? thumbnailUrl}) =>
      ScanningScoreCard(
        key: ValueKey('scanning-${job.jobId}'),
        title: title,
        job: job,
        thumbnailUrl: thumbnailUrl,
        onTap: () => _openJob(job, title),
        onLongPress: () => _cancelScan(job),
        onRetry: () =>
            ref.read(processingJobsProvider.notifier).retry(job.jobId),
      );

  List<Widget> _buildStateContent(
    AsyncValue<List<ScoreSummary>> library,
    Map<String, TrackedJob> jobs,
  ) {
    switch (library) {
      case AsyncData(:final value):
        final unlisted = _unlistedScanCards(jobs, {
          for (final score in value) score.scoreId,
        });
        // AC4: zero scores shows only the Add Score card, as in the mockup;
        // the header subtitle carries the empty-state message.
        if (value.isEmpty) return unlisted;
        final visible = filterLibraryEntries(
          buildLibraryEntries(value),
          _query,
        );
        if (visible.isEmpty && unlisted.isEmpty) {
          return [
            const SizedBox(height: _cardGap + _stateMessageTopGap),
            _NoResultsMessage(query: _query),
          ];
        }
        final reduceMotion = MediaQuery.disableAnimationsOf(context);
        return [
          ...unlisted,
          for (final entry in visible)
            // The Builder's context identifies this mount of the row, so a
            // delete that outlives it can tell (see _deleteViaTrash).
            Builder(
              key: ValueKey('row-${entry.scoreId}'),
              builder: (rowContext) => _RemovableRow(
                leaving: _leavingIds.contains(entry.scoreId),
                onRemoved: () => _finishRemoval(entry.scoreId),
                child: _buildRowCard(
                  entry,
                  _cardJob(jobs, entry.scoreId),
                  rowContext: rowContext,
                  reduceMotion: reduceMotion,
                ),
              ),
            ),
        ];
      case AsyncError(:final error):
        final sessionExpired = error is SessionExpiredException;
        return [
          const SizedBox(height: _cardGap),
          _LoadErrorPanel(
            message: _loadErrorMessage(error),
            actionLabel: sessionExpired
                ? LibraryMessages.logInAgain
                : LibraryMessages.retry,
            onAction: sessionExpired
                ? _returnToLogin
                : () => ref.read(scoreLibraryProvider.notifier).reload(),
          ),
        ];
      default:
        return const [SizedBox(height: _cardGap), _LoadingSkeletons()];
    }
  }

  /// The same row shows the processing card while its scan runs and the
  /// normal card afterwards, so completion changes it in place (AC4). A
  /// running scan can't be swiped or trashed: Cancel scan is its way out.
  Widget _buildRowCard(
    LibraryEntry entry,
    TrackedJob? job, {
    required BuildContext rowContext,
    required bool reduceMotion,
  }) {
    if (job != null && job.isRunning) {
      return Padding(
        padding: const EdgeInsets.only(top: _cardGap),
        child: _scanningCard(
          job,
          entry.displayTitle,
          thumbnailUrl: entry.score.thumbnailUrl,
        ),
      );
    }
    return _buildDismissibleCard(
      entry,
      scanFailed: job != null,
      rowContext: rowContext,
      reduceMotion: reduceMotion,
    );
  }

  Widget _buildDismissibleCard(
    LibraryEntry entry, {
    required bool scanFailed,
    required BuildContext rowContext,
    required bool reduceMotion,
  }) {
    final scoreId = entry.scoreId;
    final isDeleting = _deletingIds.contains(scoreId);
    // The gap sits inside the Dismissible so it collapses with the card.
    const gap = EdgeInsets.only(top: _cardGap);
    return Dismissible(
      key: ValueKey('dismiss-$scoreId'),
      direction: isDeleting
          ? DismissDirection.none
          : DismissDirection.endToStart,
      // Same dialog and same wait-for-the-server as the trash icon:
      // returning false (cancel or failure) snaps the card back.
      confirmDismiss: (_) => _deleteViaSwipe(entry, rowContext),
      onDismissed: (_) => _finishRemoval(scoreId),
      movementDuration: reduceMotion ? Duration.zero : _swipeMoveDuration,
      resizeDuration: reduceMotion ? null : _swipeResizeDuration,
      background: Padding(
        padding: gap,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: AppTheme.errorRed,
            borderRadius: BorderRadius.circular(_cardRadius),
          ),
          child: Align(
            alignment: Alignment.centerRight,
            child: Padding(
              padding: const EdgeInsets.only(right: _swipeIconInset),
              child: isDeleting
                  ? const SizedBox.square(
                      dimension: _swipeSpinnerSize,
                      child: CircularProgressIndicator(
                        strokeWidth: _swipeSpinnerStroke,
                        color: Colors.white,
                        semanticsLabel: LibraryMessages.deleting,
                      ),
                    )
                  : const Icon(
                      Icons.delete_rounded,
                      size: _swipeIconSize,
                      color: Colors.white,
                    ),
            ),
          ),
        ),
      ),
      child: Padding(
        padding: gap,
        child: ScoreCard(
          key: ValueKey(scoreId),
          entry: entry,
          isDeleting: isDeleting,
          scanFailed: scanFailed,
          onTap: () => _openScore(entry),
          onDelete: () => _deleteViaTrash(entry, rowContext),
        ),
      ),
    );
  }

  static String _loadErrorMessage(Object error) => switch (error) {
    SessionExpiredException() => LibraryMessages.sessionExpired,
    ScoreLibraryNetworkException() => LibraryMessages.loadNetworkError,
    _ => LibraryMessages.loadServerError,
  };
}

class _LoadingSkeletons extends StatelessWidget {
  const _LoadingSkeletons();

  static const int _count = 3;
  static const double _gap = 18;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      key: const Key('library-loading'),
      label: LibraryMessages.loadingSemantics,
      liveRegion: true,
      container: true,
      excludeSemantics: true,
      child: Column(
        children: [
          for (var i = 0; i < _count; i++) ...[
            if (i > 0) const SizedBox(height: _gap),
            const ScoreCardSkeleton(),
          ],
        ],
      ),
    );
  }
}

/// AC6 error state, reusing the auth screens' banner and pill button so
/// failures look the same across the app.
class _LoadErrorPanel extends StatelessWidget {
  const _LoadErrorPanel({
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  static const double _gap = 16;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('library-error'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AuthErrorBanner(message: message),
        const SizedBox(height: _gap),
        PrimaryPillButton(
          label: actionLabel,
          onPressed: onAction,
          // White 14 sp on the brand primaryBlue is 4.3:1, under AA; the
          // header's AA-darkened bottom stop (4.5:1) keeps it in the
          // library's own blue.
          backgroundColor: AppTheme.libraryHeaderBottom,
        ),
      ],
    );
  }
}

/// Search returned nothing although the library isn't empty — kept visibly
/// different from the AC4 empty state, which tells the user to capture.
class _NoResultsMessage extends StatelessWidget {
  const _NoResultsMessage({required this.query});

  final String query;

  static const double _headingToHintGap = 4;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Semantics(
      key: const Key('library-no-results'),
      liveRegion: true,
      container: true,
      child: Column(
        children: [
          Text(
            LibraryMessages.noResultsTitle,
            textAlign: TextAlign.center,
            style: textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppTheme.libraryCardTitle,
            ),
          ),
          const SizedBox(height: _headingToHintGap),
          Text(
            LibraryMessages.noResultsHint(query),
            textAlign: TextAlign.center,
            style: textTheme.bodyMedium?.copyWith(
              color: AppTheme.libraryScoreSubtitle,
            ),
          ),
        ],
      ),
    );
  }
}

/// A list row that can play a short collapse-and-fade exit once its score
/// is confirmed deleted via the trash icon, then reports [onRemoved] so the
/// caller drops it from the list. With reduce motion the exit is instant.
class _RemovableRow extends StatefulWidget {
  const _RemovableRow({
    required this.leaving,
    required this.onRemoved,
    required this.child,
  });

  final bool leaving;
  final VoidCallback onRemoved;
  final Widget child;

  @override
  State<_RemovableRow> createState() => _RemovableRowState();
}

class _RemovableRowState extends State<_RemovableRow>
    with SingleTickerProviderStateMixin {
  static const Duration _exitDuration = Duration(milliseconds: 220);

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: _exitDuration,
    value: 1,
  );
  late final Animation<double> _curve = CurvedAnimation(
    parent: _controller,
    curve: Curves.easeInOut,
  );

  bool _reported = false;

  /// Reports the removal once, after the current frame: [onRemoved]
  /// changes the parent's state, which is not allowed mid-build or
  /// mid-dispose.
  void _reportRemovedAfterFrame() {
    if (_reported) return;
    _reported = true;
    final onRemoved = widget.onRemoved;
    WidgetsBinding.instance.addPostFrameCallback((_) => onRemoved());
  }

  @override
  void initState() {
    super.initState();
    // Remounted after its score was confirmed deleted (e.g. a search hid
    // it mid-exit): nothing to animate, just finish the removal.
    if (widget.leaving) _reportRemovedAfterFrame();
  }

  @override
  void didUpdateWidget(_RemovableRow oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.leaving || oldWidget.leaving) return;
    if (MediaQuery.disableAnimationsOf(context)) {
      _reportRemovedAfterFrame();
    } else {
      _controller.reverse().then((_) {
        if (mounted) _reportRemovedAfterFrame();
      });
    }
  }

  @override
  void dispose() {
    // Unmounted mid-exit (a search hid the row): the animation's future
    // never completes, so finish the removal here or the score would stay
    // in the list and the header count.
    if (widget.leaving) _reportRemovedAfterFrame();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizeTransition(
      sizeFactor: _curve,
      alignment: Alignment.topCenter,
      child: FadeTransition(opacity: _curve, child: widget.child),
    );
  }
}
