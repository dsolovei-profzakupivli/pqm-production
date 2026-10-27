import unittest
from datetime import datetime, timezone
import scheduler_runtime as scheduler

def at(raw): return datetime.fromisoformat(raw.replace('Z','+00:00'))

class SandboxConfiguredDstScheduleTests(unittest.TestCase):
    def test_configured_minutes_survive_both_transitions(self):
        for minute in (0,5,17,37,59):
            spec={'kind':'hourly','minute':minute}
            for raw in ('2026-10-25T00:00:00Z','2026-10-25T01:00:00Z','2027-03-28T01:00:00Z'):
                now=at(raw)
                if minute==0: now=now.replace(minute=59)
                target=scheduler.next_run(spec,now)
                self.assertGreater(target.astimezone(timezone.utc),now)
                self.assertEqual(target.minute,minute)
                self.assertEqual(target.isoformat(),target.astimezone(timezone.utc).astimezone(scheduler.KYIV).isoformat())

    def test_second_fold_catchup_has_distinct_utc_slot(self):
        spec={'kind':'hourly','minute':37}
        self.assertTrue(scheduler.catchup_due(spec,at('2026-10-25T01:38:00Z'),'2026-10-25T00:40:00Z'))
        self.assertFalse(scheduler.catchup_due(spec,at('2026-10-25T01:38:00Z'),'2026-10-25T01:37:00Z'))

    def test_spring_catchup_is_not_blocked_by_nonexistent_wall_hour(self):
        spec={'kind':'hourly','minute':5}
        self.assertTrue(scheduler.catchup_due(spec,at('2027-03-28T01:06:00Z'),'2027-03-28T00:05:00Z'))

if __name__=='__main__': unittest.main()
