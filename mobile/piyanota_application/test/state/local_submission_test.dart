import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';

final _created = DateTime.utc(2026, 11, 10, 8);

LocalSubmission _row(
  String id, {
  String? jobId,
  SubmissionStatus status = SubmissionStatus.processing,
}) => LocalSubmission(
  clientSubmissionId: id,
  title: 'Ave',
  createdAt: _created,
  jobId: jobId,
  status: status,
);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('newClientSubmissionId', () {
    test('is a lower-case v4 UUID', () {
      final id = newClientSubmissionId(Random(1));
      expect(
        id,
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
      expect(newClientSubmissionId(), isNot(newClientSubmissionId()));
    });
  });

  group('LocalSubmission json', () {
    test('round-trips every field', () {
      final row = LocalSubmission(
        clientSubmissionId: 'abc',
        title: 'Ave',
        createdAt: _created,
        jobId: 'job-1',
        scoreId: 7,
        status: SubmissionStatus.failed,
        failureCode: 'queue_full',
      );
      final back = LocalSubmission.fromJson(row.toJson());
      expect(back!.toJson(), row.toJson());
      expect(back.createdAt, _created);
    });

    test('an unknown status reads as processing, a broken row is dropped', () {
      final json = _row('x').toJson()..['status'] = 'from_the_future';
      expect(
        LocalSubmission.fromJson(json)!.status,
        SubmissionStatus.processing,
      );
      expect(LocalSubmission.fromJson({'title': 'no id'}), isNull);
      expect(
        LocalSubmission.fromJson(_row('x').toJson()..['createdAt'] = 'nope'),
        isNull,
      );
    });

    test('holds no token or URL fields', () {
      expect(
        _row('x', jobId: 'j').copyWith(percentComplete: 5).toJson().keys,
        unorderedEquals([
          'percentComplete',
          'clientSubmissionId',
          'jobId',
          'scoreId',
          'title',
          'status',
          'failureCode',
          'replacesJobId',
          'createdAt',
        ]),
      );
    });
  });

  group('LocalSubmissionStore', () {
    test('saves, loads, clears; junk entries are dropped', () async {
      const store = LocalSubmissionStore();
      expect(await store.load(), isEmpty);
      await store.save([_row('a'), _row('b', jobId: 'j')]);
      expect((await store.load()).map((r) => r.clientSubmissionId), ['a', 'b']);
      await store.clear();
      expect(await store.load(), isEmpty);
      expect(LocalSubmissionStore.decode('not json'), isEmpty);
      expect(LocalSubmissionStore.decode('[1, {"title": 3}, null]'), isEmpty);
    });

    test('updates started in the same tick all land (none is lost)', () async {
      const store = LocalSubmissionStore();
      await Future.wait([
        for (var i = 0; i < 5; i++)
          store.update((rows) => [...rows, _row('c$i')]),
      ]);
      expect((await store.load()).map((r) => r.clientSubmissionId).toSet(), {
        'c0',
        'c1',
        'c2',
        'c3',
        'c4',
      });
    });

    test(
      'clear queues behind a running update (no rows written back)',
      () async {
        const store = LocalSubmissionStore();
        await store.save([_row('old')]);
        final pending = store.update((rows) => [...rows, _row('late')]);
        await store.clear();
        await pending;
        expect(await store.load(), isEmpty);
      },
    );

    test(
      'dismissals started in the same tick all land (none is lost)',
      () async {
        const store = LocalSubmissionStore();
        final at = DateTime.utc(2026, 11, 10, 8);
        await Future.wait([
          for (var i = 0; i < 5; i++)
            store.markDismissed(
              ['d$i'],
              at,
              retention: const Duration(days: 7),
            ),
        ]);
        expect((await store.loadDismissed()).keys.toSet(), {
          'd0',
          'd1',
          'd2',
          'd3',
          'd4',
        });
      },
    );

    test(
      'clear queues behind a running dismissal (nothing written back)',
      () async {
        const store = LocalSubmissionStore();
        final pending = store.markDismissed(
          ['late'],
          DateTime.utc(2026, 11, 10, 8),
          retention: const Duration(days: 7),
        );
        await store.clear();
        await pending;
        expect(await store.loadDismissed(), isEmpty);
      },
    );

    test('a failing change does not block the next update', () async {
      const store = LocalSubmissionStore();
      await expectLater(
        store.update((_) => throw StateError('boom')),
        throwsStateError,
      );
      await store.update((rows) => [...rows, _row('after')]);
      expect((await store.load()).single.clientSubmissionId, 'after');
    });
  });

  group('LocalSubmissionsController', () {
    test('begin, attach, fail, dismiss persist each step', () async {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final c = container.read(localSubmissionsProvider.notifier);

      await c.begin(clientSubmissionId: 'a', title: 'Ave', now: _created);
      expect((await const LocalSubmissionStore().load()).single.jobId, isNull);

      await c.attachJob(clientSubmissionId: 'a', jobId: 'job-1', scoreId: 3);
      var stored = (await const LocalSubmissionStore().load()).single;
      expect((stored.jobId, stored.scoreId), ('job-1', 3));

      await c.fail(clientSubmissionId: 'a', code: 'queue_full');
      stored = (await const LocalSubmissionStore().load()).single;
      expect(stored.status, SubmissionStatus.failed);
      expect(stored.failureCode, 'queue_full');

      await c.dismiss('a');
      expect(container.read(localSubmissionsProvider), isEmpty);
      expect(await const LocalSubmissionStore().load(), isEmpty);
    });

    test(
      'begin with a known id keeps createdAt and clears the failure',
      () async {
        final container = ProviderContainer();
        addTearDown(container.dispose);
        final c = container.read(localSubmissionsProvider.notifier);
        await c.begin(clientSubmissionId: 'a', title: 'Ave', now: _created);
        await c.fail(clientSubmissionId: 'a', code: 'network');
        await c.begin(
          clientSubmissionId: 'a',
          title: 'Ave',
          now: _created.add(const Duration(hours: 1)),
        );
        final row = container.read(localSubmissionsProvider).single;
        expect(row.createdAt, _created);
        expect(row.status, SubmissionStatus.processing);
        expect(row.failureCode, isNull);
      },
    );

    test('a new controller restores the rows (app restart)', () async {
      await const LocalSubmissionStore().save([_row('a'), _row('b')]);
      final container = ProviderContainer();
      addTearDown(container.dispose);
      container.read(localSubmissionsProvider);
      await container.read(localSubmissionsProvider.notifier).dismiss('b');
      expect(
        container
            .read(localSubmissionsProvider)
            .map((r) => r.clientSubmissionId),
        ['a'],
      );
    });

    test('forgetAll wipes memory and storage', () async {
      await const LocalSubmissionStore().save([_row('a')]);
      final container = ProviderContainer();
      addTearDown(container.dispose);
      container.read(localSubmissionsProvider);
      container.read(localSubmissionsProvider.notifier).forgetAll();
      await Future<void>.delayed(Duration.zero);
      expect(container.read(localSubmissionsProvider), isEmpty);
      expect(await const LocalSubmissionStore().load(), isEmpty);
    });
  });

  test('scoreFormFields sends clientSubmissionId only when given', () {
    const details = ScoreDetails(title: 'Ave');
    final sent = scoreFormFields(details, clientSubmissionId: 'abc');
    expect(
      sent.where((e) => e.key == 'clientSubmissionId').single.value,
      'abc',
    );
    expect(
      scoreFormFields(details).map((e) => e.key),
      isNot(contains('clientSubmissionId')),
    );
  });
}
