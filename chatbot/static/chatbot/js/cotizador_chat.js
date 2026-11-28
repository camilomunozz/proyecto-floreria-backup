(() => {
    const appEl = document.getElementById('cotizador-app');
    if (!appEl) return;

    const urlEnviar = appEl.dataset.urlEnviar;
    const urlLimpiar = appEl.dataset.urlLimpiar;
    const csrfToken = appEl.dataset.csrf;

    let cotizacionInicial = [];
    try {
        cotizacionInicial = JSON.parse(appEl.dataset.cotizacionInicial || '[]');
    } catch (e) {
        cotizacionInicial = [];
    }

    const chatBox = document.getElementById('chat-box');
    const input = document.getElementById('mensaje-input');
    const btn = document.getElementById('btn-enviar');
    const tbody = document.getElementById('cotizacion-tbody');
    const elNeto = document.getElementById('cot-neto');
    const elIva = document.getElementById('cot-iva');
    const elTotal = document.getElementById('cot-total');
    const btnLimpiar = document.getElementById('btn-limpiar');

    const mensajeInicialChat = '<div class="text-muted">Pregunta por precios de flores en Chile y pide agregar ítems a tu cotización.</div>';

    const formatoCLP = new Intl.NumberFormat('es-CL', {
        style: 'currency',
        currency: 'CLP',
        maximumFractionDigits: 0
    });

    function limpiarNumero(valor) {
        if (typeof valor === 'number') return Math.round(valor);
        const limpio = String(valor || '0').replace(/[^0-9.-]/g, '');
        return parseInt(parseFloat(limpio), 10) || 0;
    }

    function escaparHTML(texto) {
        const div = document.createElement('div');
        div.textContent = texto || '';
        return div.innerHTML;
    }

    function renderCotizacion(items) {
        tbody.innerHTML = '';
        let neto = 0;

        if (!Array.isArray(items) || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">Sin ítems en la cotización</td></tr>';
            elNeto.textContent = formatoCLP.format(0);
            elIva.textContent = formatoCLP.format(0);
            elTotal.textContent = formatoCLP.format(0);
            return;
        }

        items.forEach((item) => {
            const cantidad = limpiarNumero(item.cantidad) || 1;
            const precioUnit = limpiarNumero(item.precio_unitario);
            const subtotal = cantidad * precioUnit;
            neto += subtotal;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${escaparHTML(item.producto)}</td>
                <td><small class="text-muted">${escaparHTML(item.fuente || 'Referencial')}</small></td>
                <td class="text-end">${cantidad}</td>
                <td class="text-end">${formatoCLP.format(precioUnit)}</td>
                <td class="text-end">${formatoCLP.format(subtotal)}</td>
            `;
            tbody.appendChild(tr);
        });

        const iva = Math.round(neto * 0.19);
        const total = neto + iva;

        elNeto.textContent = formatoCLP.format(neto);
        elIva.textContent = formatoCLP.format(iva);
        elTotal.textContent = formatoCLP.format(total);
    }

    function agregarMensaje(remitente, texto) {
        const div = document.createElement('div');
        div.className = 'mb-3 p-2 rounded border-bottom';
        const textoEscapado = escaparHTML(texto).replace(/\n/g, '<br>');
        div.innerHTML = `<strong>${escaparHTML(remitente)}:</strong><br>${textoEscapado}`;
        chatBox.appendChild(div);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    async function enviarMensaje() {
        const texto = input.value.trim();
        if (!texto) return;

        agregarMensaje('Tú', texto);
        input.value = '';
        btn.disabled = true;

        try {
            const res = await fetch(urlEnviar, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ mensaje: texto })
            });
            const data = await res.json();

            if (!res.ok || data.error) {
                agregarMensaje('Error', data.error || 'Error al procesar el mensaje.');
                return;
            }

            agregarMensaje('Asistente', data.respuesta);

            if (Array.isArray(data.cotizacion)) {
                renderCotizacion(data.cotizacion);
            }
        } catch (e) {
            agregarMensaje('Error', 'No se pudo conectar con el servidor.');
        } finally {
            btn.disabled = false;
        }
    }

    async function limpiarSesionChat() {
        btnLimpiar.disabled = true;

        try {
            const res = await fetch(urlLimpiar, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                }
            });
            const data = await res.json();

            if (!res.ok || !data.ok) {
                agregarMensaje('Error', data.error || 'No se pudo limpiar la cotización.');
                return;
            }

            chatBox.innerHTML = mensajeInicialChat;
            renderCotizacion(data.cotizacion || []);
        } catch (e) {
            agregarMensaje('Error', 'No se pudo conectar con el servidor al limpiar.');
        } finally {
            btnLimpiar.disabled = false;
        }
    }

    renderCotizacion(cotizacionInicial);

    btn.addEventListener('click', enviarMensaje);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') enviarMensaje();
    });
    btnLimpiar.addEventListener('click', limpiarSesionChat);
})();