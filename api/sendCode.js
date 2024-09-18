export default async function handler(req, res) {
    if (req.method !== 'POST') {
        return res.status(405).json({ success: false, message: 'Method not allowed' });
    }

    const { code, conversationId } = req.body;

    if (!code || !conversationId) {
        return res.status(400).json({ success: false, message: 'Authorization code and conversationId are required' });
    }

    try {
        const fetch = (await import('node-fetch')).default;
        const webhookUrl = process.env.BOTPRESS_WEBHOOK_URL;

        // Prepare the payload with the authorization code and conversationId
        const payload = { code, conversationId };

        // Send the POST request to the webhook
        const response = await fetch(webhookUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        // Parse the response as JSON
        const data = await response.json();

        // Send success response
        res.status(200).json({ success: true, data });
    } catch (error) {
        console.error('Error:', error);
        res.status(500).json({ success: false, message: 'Failed to send POST request to webhook', error: error.message });
    }
}
