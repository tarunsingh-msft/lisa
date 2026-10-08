# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from assertpy import assert_that
from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates the Azure Site Recovery VM extension for Linux
    (Microsoft.Azure.RecoveryServices.SiteRecovery.Linux).

    Coverage starts with boot validation: install the extension with no
    settings, confirm provisioning succeeds, confirm the requested version was
    installed, confirm the VM is still reachable over SSH, then remove the
    extension.
    """,
    tags=["VM_Extension", "SiteRecoveryLinux"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class SiteRecoveryLinuxTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.RecoveryServices.SiteRecovery"
    EXTENSION_TYPE = "Linux"
    EXTENSION_KEY = "site_recovery_linux"

    @TestCaseMetadata(
        description="""
        Basic boot validation for the Site Recovery VM extension for Linux.

        Installs the explicitly requested candidate version with no settings
        and no protected settings. Verifies that extension provisioning
        succeeds, the installed patch version matches when a full version is
        supplied, and the VM remains reachable before removing the extension.

        The handler hangs in 'Creating' indefinitely when it is given an empty
        settings object, but provisions normally when the settings field is
        omitted from the request entirely (matching what 'az vm extension set'
        sends). The shared VmExtensionTestBase._install always sends
        'settings or {}', so this case installs via create_or_update directly
        with settings=None -- which the Azure SDK drops from the request -- and
        reuses the base assertion and cleanup helpers.

        No replication is configured and no recovery services vault is used, so
        this validates the handler install lifecycle only, not an end-to-end
        disaster recovery scenario.

        The candidate version is read from the 'extension_version' or
        'site_recovery_linux_version' runbook variable.
        """,
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery.linux"],
        maturity="preview",
    )
    def microsoft_azure_recoveryservices_siterecovery_linux_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._boot_validation_without_settings(node=node, log=log, variables=variables)

    def _boot_validation_without_settings(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        """
        Boot validation that installs the extension with no settings at all.

        Mirrors VmExtensionTestBase._boot_validation, but installs through
        AzureExtension.create_or_update directly with settings=None instead of
        the shared _install (which coerces empty settings to '{}'). Site
        Recovery stays in 'Creating' indefinitely with an empty settings
        object but provisions in a few minutes when the field is absent.
        """
        version = self._get_version(variables, use_default=False)
        extension = node.features[AzureExtension]

        try:
            (
                install_version,
                is_patch_version,
            ) = extension.normalize_type_handler_version(version)
        except LisaException:
            raise SkippedException(
                f"Version '{version}' is not a valid 'Major.Minor', "
                "'Major.Minor.Patch', or 'Major.Minor.Patch.Revision' value. "
                "Please set a valid version."
            )

        publisher = self._resolve_publisher(variables)
        type_ = self._resolve_type(variables)
        extension_name = f"{publisher}_{type_}_boot_validation_test"
        log.info(f"Installing extension '{extension_name}'...")
        try:
            if self.SUPPORTS_DELETE:
                extension.delete(name=extension_name, ignore_not_found=True)
            # Pass settings=None so the field is omitted from the request; an
            # empty '{}' makes the Site Recovery handler hang in 'Creating'.
            result = extension.create_or_update(
                name=extension_name,
                publisher=publisher,
                type_=type_,
                type_handler_version=install_version,
                auto_upgrade_minor_version=True,
                settings=None,
            )
            self._assert_provisioned(result, variables)

            installed_version = extension.get_installed_type_handler_version(
                extension_name
            )
            if is_patch_version:
                assert_that(
                    extension.are_type_handler_versions_equal(
                        version, installed_version
                    )
                ).described_as(
                    f"Installed extension '{extension_name}' version mismatch: "
                    f"expected '{version}', actual '{installed_version}'."
                ).is_true()
            log.info(
                f"Installed extension '{extension_name}' "
                f"version: {installed_version}"
            )
            self._assert_vm_reachable(node)
        finally:
            if self.SUPPORTS_DELETE:
                self._uninstall(node, name=extension_name)
