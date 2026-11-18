#! /bin/sh

. /usr/bin/common.src

LOADER_EXTRACT_PATH=$EXTRACT_ROOT/nor_loader
TAR_COMMAND=tar
LOADER_TAR=loader_nor.tar
MD5SUM_COMMAND=md5sum
ERR_LOADER_BADBLK_VAL=246
LED_ERROR_CODE_PLUGIN="0x51"
LED_ERROR_CODE_BADBLOCK="0x52"
LED_ERROR_CODE_GETCFG="0x53"
LED_ERROR_CODE_CETUS="0x92"
SUM_FILE=$LOADER_EXTRACT_PATH/loader_nor.md5
GET_LED_VALUE_COMMAND=getledval.elf
PFORMAT_COMMAND=ud_nor_pformat.elf
ERR_BADBLK_VAL="0x92"
GET_LED_VALUE_COMMAND=getledval.elf
SPICOMBOOT_COMMAND=ud_spicom_boot.elf
PORTSETTING_COMMAND=ud_init_spi_port_setting.elf
SPICOM_COMMAND=spicom.elf
GET_LSINUM_COMMAND=ud_read_lsi_type.elf
LSINUM_MIRA_CETUS=3
CPFIRMUP_COMMAND=ud_cp_firmup.elf
OSPI_MODE_SPI=0
OSPI_MODE_OCTAL96=1
OSPI_MODE_OCTAL192=2
OSPI_ERASE_SECTOR=2
OSPI_ERASE_BLOCK=3
GET_MIS_HEADER=ud_get_data_from_mis.elf
GET_BOOT_EXT_COMMAND=ud_get_boot_ext.elf
GET_BOOT_DEVICE_COMMAND=ud_get_boot_device.elf
BOOT_NOR=0
MP_EMMC_CP_NOR=1
MP_EMMC_CP_NONE=2

make_nor_loader_img()
{
    echo "make_nor_loader_img()"
    updater_log.sh "MAKE NOR_IMG START."
    cd "$LOADER_EXTRACT_PATH" || return $?

    $TAR_COMMAND xf $LOADER_TAR
    local _RET=$?
    if [ $_RET -ne 0 ] ; then
	$GET_LED_VALUE_COMMAND $LED_ERROR_CODE_PLUGIN
	return $_RET
    fi

    mount -t vfat /dev/nflasha8 /cp $VFAT_MOUNT_OPTION_SYNC || return $?
    local _COPY_RET=0
    for _FILE in DGU.bin MIS.bin loader_spi.bin cpapp-b.bin pcie_phy_fw.bin; do
        cp /cp/$_FILE $LOADER_EXTRACT_PATH/ || { _COPY_RET=$?; break; }
    done
    umount /cp
    local _UMOUNT_RET=$?
    [ $_COPY_RET -eq 0 ] || return $_COPY_RET
    [ $_UMOUNT_RET -eq 0 ] || return $_UMOUNT_RET

    if [ -f /tmp_updater/updater/update/backup/*/*/*.bin ]; then
        echo "use Backup in firmware"
        cp /tmp_updater/updater/update/backup/*/*/*.bin $LOADER_EXTRACT_PATH/Backup.bin || return $?
    else
        echo "use Backup on emmc"
        mount -t vfat $P2_DEV $P2_MNT_DIR $VFAT_MOUNT_OPTION_SYNC || return $?
        cp /setting/Backup.bin $LOADER_EXTRACT_PATH/
        local _BACKUP_RET=$?
        umount $P2_MNT_DIR
        local _UNMOUNT_RET=$?
        [ $_BACKUP_RET -eq 0 ] || return $_BACKUP_RET
        [ $_UNMOUNT_RET -eq 0 ] || return $_UNMOUNT_RET
    fi
    bksb.elf $LOADER_EXTRACT_PATH/Backup.bin $LOADER_EXTRACT_PATH/LdrBkupList.txt -c $LOADER_EXTRACT_PATH/LdrBkup.bin
    local _BK_RET=$?
    if [ $_BK_RET -ne 0 ] ; then
        $GET_LED_VALUE_COMMAND $LED_ERROR_CODE_GETCFG
        return $_BK_RET
    fi

    echo "Success make LdrBkup.bin"

    echo "do ud_nor_pformat.elf"
    $PFORMAT_COMMAND
    local retval=$?
    if [ $retval -eq $ERR_LOADER_BADBLK_VAL ] ; then
	$GET_LED_VALUE_COMMAND $LED_ERROR_CODE_BADBLOCK
	return $retval
    elif [ $retval -ne 0 ] ; then
	$GET_LED_VALUE_COMMAND $LED_ERROR_CODE_PLUGIN
	return $retval
    fi
    
    echo "write nor loader img OK"
    updater_log.sh "MAKE NOR_IMG END."
    return 0
}

write_nor_loader_img()
{
    updater_log.sh "WRITE NOR_IMG START."
    echo "write_nor_loader_img()"
    cd "$LOADER_EXTRACT_PATH" || return $?
    mount -t vfat /dev/nflasha8 /cp $VFAT_MOUNT_OPTION_SYNC || return $?
    cp ./nor_ldr.img /cp
    local _COPY_RET=$?
    umount /cp
    local _UMOUNT_RET=$?
    [ $_COPY_RET -eq 0 ] || return $_COPY_RET
    [ $_UMOUNT_RET -eq 0 ] || return $_UMOUNT_RET
    updater_log.sh "WRITE NOR_IMG END."
}

get_start_address_from_pformat()
{
# $1 : bin name
    local _SEC=`cat pformat_config.txt | sed -n "/$1/,/}/p" | sed -n '/start/p' | sed -e 's/ //g' -e 's/start=//g'`
    _SEC=$((_SEC*512))
    echo $_SEC
}

get_enc_opt_from_pformat()
{
# $1 : bin name
    local _ENC=`cat pformat_config.txt | sed -n "/$1/,/}/p" | sed -n '/enc/p' | sed -e 's/ //g' -e 's/enc=//g'`
    if [ "$_ENC" != "" ]; then
        _ENC="-y"
    else
        _ENC="-f"
    fi
    echo $_ENC
}

get_size_from_pformat()
{
# $1 : bin name
    local _SIZE=`cat pformat_config.txt | sed -n "/$1/,/}/p" | sed -n '/size/p' | sed -e 's/ //g' -e 's/size=//g'`
    _SIZE=$((_SIZE*512))
    echo $_SIZE
}

set_xfer_mode_from_pformat()
{
# $1 : bin name
    local _DTR=`cat pformat_config.txt | sed -n "/$1/,/}/p" | sed -n '/ddr/p' | sed -e 's/ //g' -e 's/ddr=//g'`
    if [ "$_DTR" != "" ]; then
        echo "set octal dtr mode"
        $CPFIRMUP_COMMAND -i
        local _TYPE=$?
        [ $_TYPE -ne 255 ] || return 255
        $CPFIRMUP_COMMAND -m $OSPI_MODE_OCTAL96 || return $?
        $CPFIRMUP_COMMAND -d 0 || return $?
    else
        echo "set spi mode"
        $CPFIRMUP_COMMAND -i
        local _TYPE=$?
        [ $_TYPE -ne 255 ] || return 255
        $CPFIRMUP_COMMAND -m $OSPI_MODE_SPI || return $?
    fi
}

write_flash()
{
# $1 : filename, $2 : address, $3 : cmd option
    echo "write ($1) start"
    $CPFIRMUP_COMMAND $3 $1 -a $2 || return $?
    echo "write ($1) end"
}

erase_write_flash()
{
# $1 : filename, $2 : address, $3 : size, $4 : cmd option, $5 : erase type
    echo "write ($1) start"
    local _ADD=$2
    local _SIZE=$3
    if [ $5 -eq $OSPI_ERASE_SECTOR ]; then
        echo "sector erase"
        local _SECADD=$((_ADD/4096))
        local _SECSIZE=$(((_SIZE+4095)/4096))
    else
        echo "block erase"
        local _SECADD=$((_ADD/65536))
        local _SECSIZE=$(((_SIZE+65535)/65536))
    fi
    $CPFIRMUP_COMMAND -e $5 -a $_SECADD -s $_SECSIZE || return $?
    $CPFIRMUP_COMMAND $4 $1 -a $_ADD || return $?
    echo "write ($1) end"
}

load_cp_updater()
{
    updater_log.sh "LOAD CP UPDATER START."
    echo "load_cp_updater()"
    cd "$LOADER_EXTRACT_PATH" || return $?
    $SPICOMBOOT_COMMAND -c || return $?
    $PORTSETTING_COMMAND 0 || return $?

    $SPICOM_COMMAND d 0xfe040000 $LOADER_EXTRACT_PATH/nor_ldr.img || return $?
    ENTRY=`cat pformat_config.txt | sed  -n '/loader_nor.bin/,/load/p' | sed -e 's/ //g' | sed -n '/load=/p' | sed -e 's/load=//g'` || return $?
    $SPICOM_COMMAND d $ENTRY $LOADER_EXTRACT_PATH/loader_spi.bin || return $?
    echo "spi loader entry:$ENTRY"
    $SPICOM_COMMAND e $ENTRY || return $?

    echo "wait link up"
    $CPFIRMUP_COMMAND -l
    local _STATUS=$?
    if [ $_STATUS -eq 255 ]; then
        echo "link up ng"
        updater_log.sh "link up NG."
        $GET_LED_VALUE_COMMAND $LED_ERROR_CODE_CETUS
        return $_STATUS
    fi
    insmod /usr/kmod/pci_ep_cp.ko || return $?

    $CPFIRMUP_COMMAND -c
    local _STATUS=$?
    if [ $_STATUS -eq 255 ]; then
        echo "check stby ng"
        updater_log.sh "STBY NG."
        $GET_LED_VALUE_COMMAND $LED_ERROR_CODE_CETUS
        return $_STATUS

    else
        echo "xfer cp updater"
        $CPFIRMUP_COMMAND -u /tmp_updater/updater/bodyfs/cp/tomco.txt -a 0x100000 || return $?
        $CPFIRMUP_COMMAND -u /tmp_updater/updater/bodyfs/cp/udtrcp.bin -a 0x108000 || return $?
        $CPFIRMUP_COMMAND -u $LOADER_EXTRACT_PATH//Backup.bin -a 0x4000000 || return $?
        echo "jump cp updater"
        $CPFIRMUP_COMMAND -j || return $?

        echo "save DDR Training data."
        DDRT_LEN=`$GET_MIS_HEADER ./MIS.bin 0 t_len` || return $?
        $CPFIRMUP_COMMAND -t /tmp_updater/ddrtraining.dat -a 0x3e210fc -s $DDRT_LEN || return $?
        updater_log.sh "LOAD CP UPDATER END."
        return 0
    fi
}

nor_update()
{
    echo "init cp updater"
    updater_log.sh "NOR_FLASH START."
    $CPFIRMUP_COMMAND -i
    FTYPE=$?
    if [ $FTYPE -eq 255 ]; then
        echo "init cp updater ng"
        updater_log.sh "CP UPDATER NG."
        $GET_LED_VALUE_COMMAND $LED_ERROR_CODE_CETUS
        return $FTYPE
    else
        $PFORMAT_COMMAND -f $FTYPE || return $?
        echo "nor type:$FTYPE"

        echo "set spi mode"
        $CPFIRMUP_COMMAND -m $OSPI_MODE_SPI || return $?

        dd if=./nor_ldr.img of=./infomisc.dat bs=512 count=4 || return $?
        ADD=0
        SIZE=$((71*512))
        OPT="-f"
        erase_write_flash ./infomisc.dat $ADD $SIZE $OPT $OSPI_ERASE_SECTOR || return $?

        ADD=`get_start_address_from_pformat DGU.bin` || return $?
        OPT=`get_enc_opt_from_pformat DGU.bin` || return $?
        write_flash ./DGU.bin $ADD $OPT || return $?

        ADD=`get_start_address_from_pformat LdrBkup.bin` || return $?
        OPT=`get_enc_opt_from_pformat LdrBkup.bin` || return $?
        write_flash ./LdrBkup.bin $ADD $OPT || return $?

        ADD=`get_start_address_from_pformat loader_nor.bin` || return $?
        SIZE=`get_size_from_pformat loader_nor.bin` || return $?
        OPT=`get_enc_opt_from_pformat loader_nor.bin` || return $?
        erase_write_flash ./loader_nor.bin $ADD $SIZE $OPT $OSPI_ERASE_SECTOR || return $?

        ADD=`get_start_address_from_pformat MIS.bin` || return $?
        SIZE=`get_size_from_pformat MIS.bin` || return $?
        OPT=`get_enc_opt_from_pformat MIS.bin` || return $?
        set_xfer_mode_from_pformat MIS.bin || return $?
        erase_write_flash ./MIS.bin $ADD $SIZE $OPT $OSPI_ERASE_SECTOR || return $?
        DDRT_ST=`$GET_MIS_HEADER ./MIS.bin 0 t_add` || return $?
        write_flash /tmp_updater/ddrtraining.dat $((ADD+DDRT_ST)) $OPT || return $?

        ADD=`get_start_address_from_pformat pcie_phy_fw.bin` || return $?
        SIZE=`wc -c < pcie_phy_fw.bin` || return $?
        OPT=`get_enc_opt_from_pformat pcie_phy_fw.bin` || return $?
        set_xfer_mode_from_pformat pcie_phy_fw.bin || return $?
        erase_write_flash ./pcie_phy_fw.bin $ADD $SIZE $OPT $OSPI_ERASE_SECTOR || return $?

        ADD=`get_start_address_from_pformat cpapp-b.bin` || return $?
        SIZE=`wc -c < ./cpapp-b.bin` || return $?
        OPT=`get_enc_opt_from_pformat cpapp-b.bin` || return $?
        set_xfer_mode_from_pformat cpapp-b.bin || return $?
        erase_write_flash ./cpapp-b.bin $ADD $SIZE $OPT $OSPI_ERASE_BLOCK || return $?
    fi
    updater_log.sh "NOR_FLASH END."
    return 0
}

update_ddrtraining()
{
    echo "update_ddrtraining"
    ADD=`get_start_address_from_pformat MIS.bin` || return $?
    DDRT_ST=`$GET_MIS_HEADER ./MIS.bin 0 t_add` || return $?
    $PFORMAT_COMMAND -m /tmp_updater/ddrtraining.dat $((ADD+DDRT_ST))
}

make_nor_loader_img || exit $?

$GET_LSINUM_COMMAND
LSINUM=$?
[ $LSINUM -ne 255 ] || exit 255
echo "LSI num : $LSINUM"
if [ $LSINUM -eq $LSINUM_MIRA_CETUS ] ; then
        $GET_BOOT_EXT_COMMAND
        BOOTEXT=$?
        [ $BOOTEXT -ne 255 ] || exit 255
	load_cp_updater || exit $?
	echo "C_BOOT_EXT : $BOOTEXT"
	if [ $BOOTEXT -eq $BOOT_NOR ] ; then
		$GET_BOOT_DEVICE_COMMAND
		BOOTDEVICE=$?
		[ $BOOTDEVICE -ne 255 ] || exit 255
		echo "BOOT_DEVICE : $BOOTDEVICE"
		if [ $BOOTDEVICE -ne $MP_EMMC_CP_NONE ] ; then
			nor_update
			RET=$?
			if [ $RET -ne 0 ]; then
				exit $RET
			fi
		fi
	fi
fi
update_ddrtraining || exit $?
write_nor_loader_img || exit $?

exit $?
