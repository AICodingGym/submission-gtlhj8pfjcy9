from unittest import skipUnless

from django.db import connection, models
from django.test import TestCase
from django.test.utils import CaptureQueriesContext


class Job(models.Model):
    guid = models.CharField(max_length=50)


class TextLogStep(models.Model):
    job = models.ForeignKey(Job, models.CASCADE)
    # Not needed to perform the cascade.
    name = models.TextField()


class TextLogError(models.Model):
    # Referencing TextLogStep with CASCADE prevents TextLogStep from being
    # fast-deleted, so its rows have to be fetched by the collector.
    step = models.ForeignKey(TextLogStep, models.CASCADE)
    line = models.TextField()


class DeleteOnlyRequiredFieldsTests(TestCase):
    def test_collector_fetches_only_required_fields(self):
        job = Job.objects.create(guid='abc')
        step = TextLogStep.objects.create(job=job, name='step')
        TextLogError.objects.create(step=step, line='error')

        with CaptureQueriesContext(connection) as ctx:
            Job.objects.filter(guid='abc').delete()

        step_table = connection.ops.quote_name(TextLogStep._meta.db_table)
        name_column = connection.ops.quote_name('name')
        step_selects = [
            q['sql'] for q in ctx.captured_queries
            if q['sql'].startswith('SELECT') and ('FROM %s' % step_table) in q['sql']
        ]
        self.assertTrue(step_selects)
        for sql in step_selects:
            self.assertNotIn(name_column, sql)
        self.assertFalse(Job.objects.exists())
        self.assertFalse(TextLogStep.objects.exists())
        self.assertFalse(TextLogError.objects.exists())

    @skipUnless(connection.vendor == 'sqlite', 'Invalid UTF-8 is inserted via SQLite.')
    def test_delete_with_undecodable_unneeded_field(self):
        """
        Reproduces the reported UnicodeDecodeError: a column that isn't
        needed for the delete contains bytes that aren't valid UTF-8.
        """
        job = Job.objects.create(guid='abc')
        step = TextLogStep.objects.create(job=job, name='step')
        TextLogError.objects.create(step=step, line='error')
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE %s SET name = CAST(X'ED' AS TEXT)" % TextLogStep._meta.db_table
            )

        Job.objects.filter(guid='abc').delete()

        self.assertFalse(Job.objects.exists())
        self.assertFalse(TextLogStep.objects.exists())
        self.assertFalse(TextLogError.objects.exists())
