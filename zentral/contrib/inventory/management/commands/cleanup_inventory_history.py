from datetime import timedelta
import logging
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger("zentral.contrib.inventory.management.commands.cleanup_inventory_history")


DELETE_MACHINE_SNAPSHOT_COMMIT_QUERY = """
DELETE FROM inventory_machinesnapshotcommit AS msc
USING (
    SELECT serial_number, source_id,
           LEAST(MAX(created_at), timestamp with time zone %s) as max_created_at
    FROM inventory_machinesnapshotcommit
    GROUP BY serial_number, source_id
) AS msc_agg
WHERE
    msc.serial_number = msc_agg.serial_number
    AND msc.source_id = msc_agg.source_id
    AND msc.created_at < msc_agg.max_created_at;
"""


ORPHANS = (
    ("inventory_machinesnapshot", "id",
     (("machine_snapshot_id", "inventory_machinesnapshotcommit"),)),
    ("inventory_puppetnode", "id",
     (("puppet_node_id", "inventory_machinesnapshot"),)),
    ("inventory_systeminfo", "id",
     (("system_info_id", "inventory_machinesnapshot"),)),
    ("inventory_teamviewer", "id",
     (("teamviewer_id", "inventory_machinesnapshot"),)),
    ("inventory_osversion", "id",
     (("os_version_id", "inventory_machinesnapshot"),)),
    ("inventory_debpackage", "id",
     (("debpackage_id", "inventory_machinesnapshot_deb_packages"),)),
    ("inventory_machinegroup", "id",
     (("machinegroup_id", "inventory_machinesnapshot_groups"),)),
    ("inventory_link", "id",
     (("link_id", "inventory_machinesnapshot_links"),
      ("link_id", "inventory_machinegroup_links"),
      ("link_id", "inventory_machinegroup_machine_links"),
      ("link_id", "inventory_businessunit_links"))),
    ("inventory_networkinterface", "id",
     (("networkinterface_id", "inventory_machinesnapshot_network_interfaces"),)),
    ("inventory_osxappinstance", "id",
     (("osxappinstance_id", "inventory_machinesnapshot_osx_app_instances"),)),
    ("inventory_certificate", "id",
     (("signed_by_id", "inventory_osxappinstance"),
      ("signed_by_id", "inventory_certificate"),
      ("signed_by_id", "santa_collectedapplication"))),
    ("inventory_osxapp", "id",
     (("app_id", "inventory_osxappinstance"),
      ("bundle_id", "santa_collectedapplication"))),
)


class Command(BaseCommand):
    help = "Cleanup inventory history"

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='number of days to keep, default 30')

    def set_options(self, **options):
        self.min_date = timezone.now() - timedelta(days=options["days"])

    def handle(self, *args, **kwargs):
        self.set_options(**kwargs)
        with transaction.atomic():
            with connection.cursor() as cursor:
                self.cleanup_inventory_history(cursor)

    def cleanup_inventory_history(self, cursor):
        # delete older machine snapshot commits
        cursor.execute(DELETE_MACHINE_SNAPSHOT_COMMIT_QUERY, [self.min_date])
        print("machine snapshot commits", cursor.rowcount)

        # orphans
        for table_name, attribute, links in ORPHANS:
            wheres = []
            for fk_attribute, fk_table in links:
                wheres.append("{} NOT IN (SELECT DISTINCT {} FROM {} WHERE {} IS NOT NULL)".format(
                              attribute, fk_attribute, fk_table, fk_attribute))
            query = "DELETE FROM {} WHERE {}".format(table_name, " AND ".join(wheres))
            cursor.execute(query)
            print(table_name, cursor.rowcount)
