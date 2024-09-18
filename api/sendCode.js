export default async function handler(req, res) {
    if (req.method === 'POST') {
        const { code } = req.body;

        if (!code) {
            return res.status(400).json({ success: false, message: 'Authorization code is required' });
        }

        try {
            const fetch = (await import('node-fetch')).default;

            const webhookUrl = process.env.BOTPRESS_WEBHOOK_URL;
            const clientId = process.env.STRAVA_CLIENT_ID;
            const clientSecret = process.env.STRAVA_CLIENT_SECRET;

            if (!webhookUrl || !clientId || !clientSecret) {
                return res.status(500).json({ success: false, message: 'Missing environment variables' });
            }

            // Prepare the payload with the authorization code
            const payload = {
                code,
                conversationId: 'conv_01J82FTZNZEP72YQFKANNZNMFK'
            };

            // Send the POST request to the webhook
            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            // Log response details
            console.log('Response Status:', response.status);
            console.log('Response Headers:', response.headers.raw());

            // Handle response
            const contentType = response.headers.get('Content-Type');
            let data;
            if (contentType && contentType.includes('application/json')) {
                const text = await response.text();
                data = text ? JSON.parse(text) : {};
            } else {
                data = await response.text();
            }

            res.status(200).json({ success: true, data });
        } catch (error) {
            console.error('Error:', error);
            res.status(500).json({ success: false, message: 'Failed to send POST request to webhook', error: error.message });
        }
    } else {
        res.status(405).json({ success: false, message: 'Method not allowed' });
    }
}
