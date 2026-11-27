
document.addEventListener("DOMContentLoaded", () => {

    // =========================================
    // CONFIGURACIÓN
    // =========================================

    const API_URL = "/chatbot_usuario/api/chat/";
    const CART_URL = "/carrito/agregar/";

    const toggleButton = document.getElementById("chatbot-toggle");
    const chatWindow = document.getElementById("chatbot-window");
    const closeButton = document.getElementById("chatbot-close");
    const messagesContainer = document.getElementById("chatbot-messages");
    const chatForm = document.getElementById("chatbot-form");
    const chatInput = document.getElementById("chatbot-input");
    const sendButton = document.getElementById("chatbot-send");

    if (
        !toggleButton ||
        !chatWindow ||
        !closeButton ||
        !messagesContainer ||
        !chatForm ||
        !chatInput
    ) {
        console.error("FlowerView: No se encontraron todos los elementos del chatbot.");
        return;
    }

    let isSending = false;

    // =========================================
    // ABRIR Y CERRAR CHATBOT
    // =========================================

    function openChat() {
        chatWindow.hidden = false;
        chatWindow.classList.add("active");
        toggleButton.setAttribute("aria-expanded", "true");

        chatInput.focus();
    }

    function closeChat() {
        chatWindow.hidden = true;
        chatWindow.classList.remove("active");
        toggleButton.setAttribute("aria-expanded", "false");
    }

    toggleButton.addEventListener("click", openChat);
    closeButton.addEventListener("click", closeChat);

    // =========================================
    // CSRF
    // =========================================

    function getCsrfToken() {
        const csrfInput = chatForm.querySelector(
            '[name="csrfmiddlewaretoken"]'
        );

        return csrfInput ? csrfInput.value : "";
    }

    // =========================================
    // MENSAJES
    // =========================================

    function addMessage(text, sender = "chatbot-message-bot") {
        const message = document.createElement("div");

        message.classList.add("chatbot-message", sender);
        message.textContent = text;

        messagesContainer.appendChild(message);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        return message;
    }

    // =========================================
    // INDICADOR DE ESCRITURA
    // =========================================

    function showTypingIndicator() {
        const indicator = document.createElement("div");

        indicator.classList.add(
            "chatbot-message",
            "chatbot-message-bot"
        );

        indicator.id = "chatbot-typing";
        indicator.textContent = "FlowerView está escribiendo...";

        messagesContainer.appendChild(indicator);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById("chatbot-typing");

        if (indicator) {
            indicator.remove();
        }
    }

    // =========================================
    // FORMATO DE PRECIOS
    // =========================================

    function formatPrice(price) {
        const amount = Number(price);

        if (!Number.isFinite(amount)) {
            return "$" + price;
        }

        return new Intl.NumberFormat("es-CL", {
            style: "currency",
            currency: "CLP",
            maximumFractionDigits: 0
        }).format(amount);
    }

    // =========================================
    // ACTUALIZAR CONTADOR DEL CARRITO
    // =========================================

    function updateCartCounter(cantidad) {
        const counter = document.getElementById("cantidad_carrito");

        if (counter) {
            counter.textContent = cantidad;
        }

        localStorage.setItem("cart_count", String(cantidad));
    }

    // =========================================
    // CREAR TARJETA DE PRODUCTO
    // =========================================

    function createProductCard(product) {
        const card = document.createElement("div");
        card.classList.add("chatbot-product-card");

        // Imagen
        const imageContainer = document.createElement("div");
        imageContainer.classList.add("chatbot-product-image-container");

        const image = document.createElement("img");

        image.classList.add("chatbot-product-image");
        image.alt = product.nombre || "Producto FlowerView";
        image.loading = "lazy";

        if (product.imagen) {
            image.src = product.imagen;
        } else {
            imageContainer.classList.add("no-image");
        }

        imageContainer.appendChild(image);

        // Información
        const information = document.createElement("div");
        information.classList.add("chatbot-product-information");

        const name = document.createElement("h4");
        name.classList.add("chatbot-product-name");
        name.textContent = product.nombre || "Producto";

        const description = document.createElement("p");
        description.classList.add("chatbot-product-description");
        description.textContent = product.descripcion || "";

        const price = document.createElement("p");
        price.classList.add("chatbot-product-price");
        price.textContent = formatPrice(product.precio);

        // Botón carrito
        const button = document.createElement("button");

        button.type = "button";
        button.classList.add("chatbot-add-cart");
        button.textContent = "Agregar al carrito";

        button.addEventListener("click", () => {
            addToCart(product, button);
        });

        information.appendChild(name);
        information.appendChild(description);
        information.appendChild(price);
        information.appendChild(button);

        card.appendChild(imageContainer);
        card.appendChild(information);

        return card;
    }

    // =========================================
    // MOSTRAR PRODUCTOS
    // =========================================

    function showProducts(products) {
        if (!Array.isArray(products) || products.length === 0) {
            return;
        }

        const container = document.createElement("div");
        container.classList.add("chatbot-products-container");

        const title = document.createElement("h4");

        title.classList.add("chatbot-products-title");
        title.textContent = "Productos recomendados";

        container.appendChild(title);

        products.slice(0, 3).forEach(product => {
            if (product.id) {
                container.appendChild(createProductCard(product));
            }
        });

        if (container.children.length > 1) {
            messagesContainer.appendChild(container);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    }

    // =========================================
    // AGREGAR AL CARRITO
    // =========================================

    async function addToCart(product, button) {
        if (button.disabled) {
            return;
        }

        const originalText = button.textContent;

        button.disabled = true;
        button.textContent = "Agregando...";

        try {
            const csrfToken = getCsrfToken();

            if (!csrfToken) {
                throw new Error("No se encontró el token CSRF.");
            }

            const formData = new URLSearchParams();

            formData.append("action", "post");
            formData.append("producto_id", product.id);
            formData.append("cantidad", "1");

            const response = await fetch(CART_URL, {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": csrfToken
                },
                credentials: "same-origin",
                body: formData.toString()
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.error || "No se pudo agregar el producto."
                );
            }

            // Actualizar contador de la navbar
            if (data.cantidad !== undefined) {
                updateCartCounter(data.cantidad);
            }

            button.textContent = "✓ Agregado al carrito";

            addMessage(
                `${data.nombre || product.nombre} se agregó a tu carrito. 🌷`
            );

        } catch (error) {
            console.error("Error al agregar al carrito:", error);

            button.disabled = false;
            button.textContent = originalText;

            addMessage(
                "No pudimos agregar el producto al carrito. Inténtalo nuevamente."
            );
        }
    }

    // =========================================
    // ENVIAR MENSAJE
    // =========================================

    async function sendMessage(message) {
        if (!message || isSending) {
            return;
        }

        isSending = true;

        chatInput.disabled = true;

        if (sendButton) {
            sendButton.disabled = true;
        }

        addMessage(message, "chatbot-message-user");
        showTypingIndicator();

        try {
            const response = await fetch(API_URL, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken()
                },
                credentials: "same-origin",
                body: JSON.stringify({
                    mensaje: message
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.error || "No se pudo obtener una respuesta."
                );
            }

            removeTypingIndicator();

            if (data.respuesta) {
                addMessage(data.respuesta);
            }

            showProducts(data.productos);

        } catch (error) {
            console.error("Error en el chatbot:", error);

            removeTypingIndicator();

            addMessage(
                "Lo siento, ocurrió un problema al procesar tu mensaje. Inténtalo nuevamente. 🌷"
            );

        } finally {
            removeTypingIndicator();

            isSending = false;

            chatInput.disabled = false;

            if (sendButton) {
                sendButton.disabled = false;
            }

            chatInput.focus();
        }
    }

    // =========================================
    // FORMULARIO
    // =========================================

    chatForm.addEventListener("submit", event => {
        event.preventDefault();

        const message = chatInput.value.trim();

        if (!message || isSending) {
            return;
        }

        chatInput.value = "";

        sendMessage(message);
    });

});
