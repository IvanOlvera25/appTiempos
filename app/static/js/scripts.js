$(document).ready(function() {
    /********************************************************************
     * 1. Inicializar Select2 para Empleados
     ********************************************************************/
    function initializeSelect2() {
        const employeeSelect = $('#employee_search');
        if (employeeSelect.length) {
            employeeSelect.select2({
                theme: 'bootstrap4',
                placeholder: 'Selecciona un empleado',
                allowClear: true
            });
            // Cuando se selecciona un empleado con select2
            employeeSelect.on('select2:select', function(e) {
                const selectedId = e.params.data.id;
                console.log("Select2 - Empleado seleccionado:", selectedId);
                $('#employee_id_hidden').val(selectedId);
                $('#qrErrorToast').hide();
                $('#goToProjectBtn').prop('disabled', false);
            });
            employeeSelect.on('select2:clear', function() {
                console.log("Select2 - Selección limpiada");
                $('#employee_id_hidden').val('');
                $('#qrErrorToast').hide();
                $('#goToProjectBtn').prop('disabled', true);
            });
        }
    }
    initializeSelect2();

    // Además, para asegurarnos en caso de que se use el evento change en el select
    $('#employee_search').on('change', function() {
       const selectedId = $(this).val();
       console.log("Change event - Empleado seleccionado:", selectedId);
       $('#employee_id_hidden').val(selectedId);
       if (selectedId) {
           $('#goToProjectBtn').prop('disabled', false);
       } else {
           $('#goToProjectBtn').prop('disabled', true);
       }
    });
});
    /********************************************************************
     * 2. Botones para Registro Manual vs Escaneo
     ********************************************************************/
    const manualRegisterBtn = $('#manual-register-btn');
    const manualRegistration = $('#manual-registration');
    const qrScannerSection = $('#qr-scanner-section');
    const backToScannerBtn = $('#back-to-scanner-btn');
    const registerTimeForm = $('#register-time-form');

    if (manualRegisterBtn.length && manualRegistration.length &&
        qrScannerSection.length && backToScannerBtn.length && registerTimeForm.length) {

        manualRegisterBtn.on('click', function() {
            qrScannerSection.hide();
            manualRegistration.show();
            registerTimeForm[0].reset();
            $('#employee_search').val(null).trigger('change');
            $('#employee_id_hidden').val('');
        });

        backToScannerBtn.on('click', function() {
            manualRegistration.hide();
            qrScannerSection.show();
            registerTimeForm[0].reset();
            $('#employee_search').val(null).trigger('change');
            $('#employee_id_hidden').val('');
            const projectSelectionCards = $('.project-card');
            projectSelectionCards.removeClass('selected');
            $('#project_id_hidden').val('');
        });
    }

    /********************************************************************
     * 3. Manejo de la Cámara y Escaneo QR con selección de cámara
     ********************************************************************/
    const readerStatus = $('#qr-reader-status');
    const video = $('#video');

    // Asegúrate de tener un <select id="cameraSelect"> en tu HTML.
    // Si no existe, lo creamos e insertamos al inicio de la sección de escaneo.
    let cameraSelect = $('#cameraSelect');
    if (cameraSelect.length === 0) {
        cameraSelect = $('<select id="cameraSelect" class="form-select w-auto mb-2"></select>');
        // Se inserta antes del video
        $('#qr-scanner-section').prepend(cameraSelect);
    }

    let currentDeviceId = null;
    let codeReader = null;

    // 3a. Enumerar dispositivos de video y poblar el <select>
    async function listVideoInputDevices() {
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const videoDevices = devices.filter(d => d.kind === 'videoinput');
            console.log('Cámaras detectadas:', videoDevices);

            cameraSelect.empty();
            if (videoDevices.length === 0) {
                cameraSelect.append('<option value="">No se encontraron cámaras</option>');
                readerStatus.text('No se encontraron cámaras.');
                return;
            }

            videoDevices.forEach((device, index) => {
                const label = device.label || `Cámara ${index + 1}`;
                cameraSelect.append(`<option value="${device.deviceId}">${label}</option>`);
            });

            // Seleccionar la última cámara por defecto (suele ser la trasera)
            const defaultDeviceId = videoDevices[videoDevices.length - 1].deviceId;
            cameraSelect.val(defaultDeviceId);
            currentDeviceId = defaultDeviceId;
        } catch (err) {
            console.error('[listVideoInputDevices] Error:', err);
            readerStatus.text(`Error al listar cámaras: ${err.message}`);
        }
    }

    // 3b. Iniciar el escaneo con el deviceId seleccionado
    async function startScanningQR(deviceId) {
        if (!deviceId) {
            readerStatus.text('No hay cámara seleccionada.');
            return;
        }
        try {
            if (codeReader) {
                codeReader.reset();
            }
            codeReader = codeReader = new ZXing.BrowserMultiFormatReader();
            console.log('Iniciando escaneo con cameraId:', deviceId);

            codeReader.decodeFromVideoDevice(deviceId, 'video', (result, err) => {
                if (result) {
                    handleQrScan(result.text);
                }
                if (err && !(err instanceof ZXing.NotFoundException)) {
                    console.error('[startScanningQR] Error decodificando:', err);
                    readerStatus.text(`Error: ${err.message}`);
                }
            });
            readerStatus.text('Escaneando...');
        } catch (error) {
            console.error('[startScanningQR] Error general:', error);
            readerStatus.text(`Error al iniciar escaneo: ${error.message}`);
        }
    }

    // 3c. Cuando el usuario cambia la cámara en el <select>
    cameraSelect.on('change', function() {
        const newDeviceId = $(this).val();
        console.log('Usuario seleccionó cámara:', newDeviceId);
        currentDeviceId = newDeviceId;
        startScanningQR(newDeviceId);
    });

    // 3d. Función para inicializar cámaras y arrancar el escaneo
    async function initCameras() {
        await listVideoInputDevices();
        if (currentDeviceId) {
            startScanningQR(currentDeviceId);
        }
    }
    initCameras();

    /********************************************************************
     * 4. Funciones para Toasts, Cuenta Regresiva, Flash y Captura de Foto
     ********************************************************************/
    function showSuccessToast(employeeName) {
        $('#employeeNameToast').text(employeeName);
        const toastEl = $('#qrSuccessToast');
        const toast = new bootstrap.Toast(toastEl[0], { delay: 5000 });
        toast.show();
    }

    function showErrorToast(errorMessage) {
        $('#errorMessageToast').text(errorMessage);
        const toastEl = $('#qrErrorToast');
        const toast = new bootstrap.Toast(toastEl[0], { delay: 5000 });
        toast.show();
    }

    // Animación de pulso para la cuenta regresiva
    function updateCountdownUI(value) {
        const msgEl = $('#countdownMessage');
        msgEl.text(value);
        msgEl.addClass('countdown-pulse');
        setTimeout(() => msgEl.removeClass('countdown-pulse'), 500);
    }

    // Muestra el toast de cuenta regresiva (centrado y decorado)
    function showCountdownToast(initialSeconds, onFinish) {
        const toastEl = document.getElementById('countdownToast');
        const countdownToast = new bootstrap.Toast(toastEl, { autohide: false });
        countdownToast.show();

        let secondsLeft = initialSeconds;
        updateCountdownUI(secondsLeft);

        const intervalId = setInterval(() => {
            secondsLeft--;
            if (secondsLeft > 0) {
                updateCountdownUI(secondsLeft);
            } else {
                clearInterval(intervalId);
                countdownToast.hide();
                doFlashEffect(() => {
                    if (onFinish) onFinish();
                });
            }
        }, 1000);
    }

    // Efecto flash: usa un overlay (#flashOverlay) que debe existir en el HTML
    function doFlashEffect(onEnd) {
        const flashOverlay = $('#flashOverlay');
        flashOverlay.addClass('flash-active');
        setTimeout(() => {
            flashOverlay.removeClass('flash-active');
            if (onEnd) onEnd();
        }, 400);
    }

    // Captura la foto del video y llama al backend; después resetea el lector
    function capturePhotoAndReset(employeeId) {
        const canvas = document.getElementById('snapshotCanvas');
        const videoElement = document.getElementById('video');
        if (!canvas) {
            console.warn('No se encontró #snapshotCanvas');
            return;
        }
        const context = canvas.getContext('2d');
        context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

        const base64Image = canvas.toDataURL('image/png');
        $.ajax({
            url: '/capture_photo',
            type: 'POST',
            data: {
                employee_id: employeeId,
                photo: base64Image
            },
            success: function(resp) {
                console.log('Foto guardada:', resp);
            },
            error: function(err) {
                console.error('Error guardando foto:', err);
            }
        });

        if (codeReader) {
            codeReader.reset();
        }
    }

    /********************************************************************
     * 5. Manejar el resultado del escaneo QR
     ********************************************************************/
    function handleQrScan(qrData) {
        console.log('[handleQrScan] QR leído:', qrData);
        if (codeReader) {
            codeReader.reset();
        }
        $.ajax({
            url: '/get_employee/' + encodeURIComponent(qrData),
            type: 'GET',
            success: function(response) {
                if (response.id) {
                    $('#employee_id_hidden').val(response.id);
                    $('#employee_search').val(response.id).trigger('change');
                    qrScannerSection.hide();
                    manualRegistration.show();
                    showSuccessToast(response.nombre_completo);
                    showCountdownToast(2, () => {
                        capturePhotoAndReset(response.id);
                    });
                } else {
                    showErrorToast('Empleado no encontrado para el QR: ' + qrData);
                    if (codeReader) codeReader.reset();
                }
            },
            error: function(xhr) {
                showErrorToast('Error consultando empleado con el QR: ' + qrData);
                if (codeReader) codeReader.reset();
            }
        });
    }

    /********************************************************************
     * 6. Escaneo de QR en Modal (Opcional)
     ********************************************************************/
    const qrModal = $('#qrModal');
    const modalVideo = $('#modal-video');
    const modalReaderStatus = $('#modal-qr-reader-status');

    if (qrModal.length && modalVideo.length && modalReaderStatus.length) {
        let modalCodeReader;
        function handleModalQrScan(qrData) {
            if (modalCodeReader) modalCodeReader.reset();
            const modalInstance = bootstrap.Modal.getInstance(qrModal[0]);
            modalInstance.hide();
            $.ajax({
                url: '/get_employee/' + encodeURIComponent(qrData),
                type: 'GET',
                success: function(response) {
                    if (response.id) {
                        $('#employee_id_hidden').val(response.id);
                        $('#employee_search').val(response.id).trigger('change');
                        qrScannerSection.hide();
                        manualRegistration.show();
                        showSuccessToast(response.nombre_completo);
                    } else {
                        showErrorToast('Empleado no encontrado (modal): ' + qrData);
                    }
                },
                error: function() {
                    showErrorToast('Error consultando empleado (modal).');
                }
            });
        }
        qrModal.on('shown.bs.modal', async function () {
            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                const videoDevices = devices.filter(d => d.kind === 'videoinput');
                const modalSelectedDeviceId = videoDevices.length ? videoDevices[videoDevices.length - 1].deviceId : null;
                if (!modalSelectedDeviceId) {
                    modalReaderStatus.text('No se encontró ninguna cámara.');
                    return;
                }
                modalCodeReader = new ZXing.BrowserQRCodeReader();
                modalCodeReader.decodeFromVideoDevice(modalSelectedDeviceId, 'modal-video', (result, err) => {
                    if (result) {
                        handleModalQrScan(result.text);
                    }
                    if (err && !(err instanceof ZXing.NotFoundException)) {
                        modalReaderStatus.text(`Error: ${err.message}`);
                    }
                });
                modalReaderStatus.text('Escaneando...');
            } catch (error) {
                modalReaderStatus.text(`Error al iniciar escaneo: ${error.message}`);
            }
        });
        qrModal.on('hidden.bs.modal', function () {
            if (modalCodeReader) {
                modalCodeReader.reset();
                modalReaderStatus.text('');
            }
        });
    }

    /********************************************************************
     * 7. Selección de Proyectos mediante Tarjetas
     ********************************************************************/
    const projectSelectionCards = $('.project-card');
    if (projectSelectionCards.length) {
        projectSelectionCards.on('click', function() {
            projectSelectionCards.removeClass('selected');
            $(this).addClass('selected');
            const projectId = $(this).data('project-id');
            $('#project_id_hidden').val(projectId);
            console.log('Proyecto seleccionado:', projectId);
        });
    }

    /********************************************************************
     * 8. Impresión: permitir múltiples activos y finalizar individualmente
     ********************************************************************/
    if (department === 'Impresion') {
        // Mostrar botones de finalizar en cada proyecto activo
        $('.finalize-project-btn').on('click', function(e) {
            e.stopPropagation();
            const projectId = $(this).data('project-id');
            const empId = $('#employee_id_hidden').val();
            $.post(`/finalize_active_record/${empId}/${projectId}`)
             .done(res => {
                if (res.success) {
                    // Eliminar marcador y botón
                    $(`.project-card[data-project-id="${projectId}"]`).removeClass('active-record');
                    $(this).remove();
                }
             });
        });
        // Al iniciar un nuevo registro, no finalizar otros
        $('#register-time-form').on('submit', function(e) {
            // Si es inicio en impresión, dejamos todo, backend permite múltiples
        });
    }

    /********************************************************************
 * 8. Verificar registro activo al seleccionar empleado
 ********************************************************************/
$('#employee_search').on('change', function() {
    var employeeId = $(this).val();
    if (!employeeId) return;
    $.ajax({
        url: '/check_active_record',
        type: 'GET',
        data: { employee_id: employeeId },
        dataType: 'json',
        success: function(data) {
            if (data.active) {
                // Si hay registro activo, ocultar el botón Iniciar y mostrar el de Finalizar
                $('#iniciar-btn-container').hide();
                $('#finalize-btn-container').show();
            } else {
                $('#iniciar-btn-container').show();
                $('#finalize-btn-container').hide();
            }
        },
        error: function(xhr) {
            console.error('Error al verificar registro activo:', xhr);
        }
    });
});

// Agregar al final de scripts.js

/********************************************************************
 * 9. Prevención de Doble Envío de Formularios
 ********************************************************************/
function preventDoubleSubmission() {
    $('form').on('submit', function(e) {
        const form = $(this);
        const submitBtn = form.find('button[type="submit"], input[type="submit"]');

        // Si ya está siendo procesado, prevenir
        if (form.data('submitting')) {
            e.preventDefault();
            return false;
        }

        // Marcar como enviando
        form.data('submitting', true);

        // Deshabilitar botones de envío
        submitBtn.prop('disabled', true);

        // Mostrar indicador de carga
        const originalText = submitBtn.text();
        submitBtn.text('Procesando...');

        // Timeout de seguridad (resetear después de 10 segundos)
        setTimeout(() => {
            form.data('submitting', false);
            submitBtn.prop('disabled', false);
            submitBtn.text(originalText);
        }, 10000);
    });
}

// Inicializar cuando el documento esté listo
$(document).ready(function() {
    preventDoubleSubmission();
});

/********************************************************************
 * 10. Prevención específica para botones de registro de tiempo
 ********************************************************************/
function preventTimeRecordDuplicates() {
    $('#iniciar-btn, .btn-success').on('click', function(e) {
        const btn = $(this);

        // Si ya está procesando, cancelar
        if (btn.data('processing')) {
            e.preventDefault();
            return false;
        }

        // Marcar como procesando
        btn.data('processing', true);
        btn.prop('disabled', true);

        const originalText = btn.text();
        btn.text('Iniciando...');

        // Resetear después de 5 segundos
        setTimeout(() => {
            btn.data('processing', false);
            btn.prop('disabled', false);
            btn.text(originalText);
        }, 5000);
    });
}

$(document).ready(function() {
    preventTimeRecordDuplicates();
});
